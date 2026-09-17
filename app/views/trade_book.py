"""Trade book: the nine SIM tickets (MASTER_SPEC Table 4, rows 2.1–2.9).

Everything shown is read from the Phase 2 outputs and inputs: `outputs/tables/trade_book.csv` (one row per ticket, the
engine-derived dates and values), `trade_hedges.csv`, `trade_eligibility_check.csv`, `trade_credit_exposure.csv`, and
`config/trades.yaml` / `config/counterparties.yaml` for the prose typed on the ticket (rationale, pricing notes, event
notes, counterparty records). Nothing is re-derived: the page splits the book's " | "-joined per-lot and per-sale
columns back into rows and formats them.

Page-local helpers (not in app/lib): `_s`/`_parts`/`_f` read the string-typed trade_book columns, `_ticket_yaml`
finds a ticket in trades.yaml, `_gantt_rows` turns a ticket's dates into timeline bars and markers.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi, day, inr_m, num, pct  # noqa: E402
from desk import HORIZON_END, WINDOW_END  # noqa: E402
from desk.reporting.style import PALETTE  # noqa: E402

BOOK = data.table_rel("trade_book")
HEDGES = data.table_rel("trade_hedges")
ELIG = data.table_rel("trade_eligibility_check")
CREDIT = data.table_rel("trade_credit_exposure")
TRADES_YAML = f"{data.CONFIG}/trades.yaml"
CPS_YAML = f"{data.CONFIG}/counterparties.yaml"
DOC = f"{data.DOCS}/20_trade_book.md"

GRADE_NAMES = {"zorba": "Zorba 95/5", "taint_tabor": "Taint/Tabor", "tense": "Tense"}
LANE_NAMES = {"JEA_NSA": "Jebel Ali → Nhava Sheva", "USEC_MUN": "US East Coast → Mundra"}
FREIGHT_COL = {"JEA_NSA": "freight_jea_nsa_usd_t", "USEC_MUN": "freight_usec_mun_usd_t"}


# ------------------------------------------------------------------------------------------------ helpers
def _s(v) -> str | None:
    """A trade_book cell as a clean string, or None when empty."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return None if s in ("", "nan", "None") else s


def _parts(v) -> list[str]:
    """Split a " | "-joined per-lot / per-sale column, keeping empty positions."""
    s = _s(v)
    return [] if s is None else [p.strip() for p in s.split("|")]


def _f(v) -> float | None:
    s = _s(v)
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _d(v, year: bool = True) -> str:
    s = _s(v)
    return "—" if s is None else day(s, year)


def _at(parts: list[str], i: int) -> str | None:
    return (parts[i] or None) if i < len(parts) else None


def _grade(g) -> str:
    return GRADE_NAMES.get(str(g), str(g))


def _lane(ln) -> str:
    return LANE_NAMES.get(str(ln), str(ln))


def _md_cell(text: str) -> str:
    return docs_text.escape_streamlit(str(text)).replace("|", "\\|").replace("\n", " ")


def _kv_table(rows: list[tuple[str, str]]) -> None:
    """A two-column markdown table (wraps long values, unlike st.dataframe)."""
    lines = ["| Field | Value |", "|---|---|"] + [f"| {_md_cell(k)} | {_md_cell(v)} |" for k, v in rows if v]
    st.markdown("\n".join(lines))


def _ticket_yaml(trades: dict | None, tid: str) -> dict | None:
    if not trades:
        return None
    return next((t for t in trades.get("trades", []) if t.get("trade_id") == tid), None)


def _label(row: pd.Series) -> str:
    return (f"{row['trade_id']} — {_grade(row['grade'])} {num(_f(row['quantity_mt']) or 0)} MT, {_lane(row['lane'])}, "
            f"{row['incoterm']}, traded {_d(row['trade_date'])}")


def _buy_price(row: pd.Series) -> str:
    if row["purchase_pricing_type"] == "FIXED":
        return f"{num(_f(row['purchase_price_usd_t']) or 0, 2)} USD/t {row['incoterm']}"
    return (f"{_s(row['purchase_factor_frac'])} × LME {(_s(row['purchase_lme_reference']) or '').lower()} average "
            f"{_d(row['pricing_period_start'], False)}–{_d(row['pricing_period_end'])}")


# ------------------------------------------------------------------------------------------------ page
spec = components.PAGE["trade_book"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)

book = data.trade_book(dtype_str=True)
elig = data.trade_eligibility_check()
trades_cfg = data.trades_yaml()
flags = data.series_flags()

if book is None:
    components.missing_data(BOOK)
    components.what_it_tells(DOC)
    st.stop()

book = book.sort_values("trade_id").reset_index(drop=True)
n = len(book)
mt = sum(_f(v) or 0 for v in book["quantity_mt"])
boxes = sum(_f(v) or 0 for v in book["boxes"])
n_pass = int((elig["status"] == "PASS").sum()) if elig is not None else None
n_fob = int((book["incoterm"] == "FOB").sum())

st.markdown(
    f"**The takeaway:** {n} simulated tickets, {num(mt)} MT in {num(boxes)} containers, each carrying the terms a "
    "physical import desk actually negotiates — an ISRI spec with a moisture franchise, an incoterm that says who "
    "books the freight, a pricing formula, an LC with a tenor, a buyer with a credit limit and a hedge sized by a "
    "written rule"
    + (f" — and {n_pass} of {len(elig)} traded only in weeks the ex-ante parity rule had open." if n_pass is not None
       else ".")
    + " The prices are the desk's own rules, not quotes (docs/20 §4), so read the P&L page's band before any margin.")

kpis = [
    Kpi("Tickets", str(n), f"traded {_d(book['trade_date'].min(), False)} to {_d(book['trade_date'].max())}"),
    Kpi("Tonnes", f"{num(mt)} MT"),
    Kpi("Containers", num(boxes), "boxes × the registered payload per box (ASSUMPTION)"),
    Kpi("Sale value", inr_m(sum(_f(v) or 0 for v in book["sale_value_inr"]), dp=0),
        "sum of `sale_value_inr`: every sale at its contracted price"),
    Kpi("FOB · CFR", f"{n_fob} · {n - n_fob}", "incoterm of the purchase"),
    Kpi("§5a rule", f"{n_pass} / {len(elig)} pass" if n_pass is not None else "n/a",
        "trade_eligibility_check.csv: open on the base, point-in-time-mix and conversion-stressed screens"),
]
components.kpi_row(kpis)
components.source_caption([BOOK, ELIG], ["SIM"], note="tickets, counterparties, vessels and banks are fictional")

tab_book, tab_card, tab_time, tab_cp, tab_elig = st.tabs(
    ["Book summary", "Ticket card", "Timeline", "Counterparties & credit", "Eligibility evidence"])

# ------------------------------------------------------------------------------------------------ book summary
with tab_book:
    st.subheader("The nine tickets")
    f1, f2, f3, f4, f5 = st.columns(5)
    opts = {c: sorted(book[c].dropna().unique()) for c in
            ("lane", "grade", "incoterm", "purchase_pricing_type", "payment_instrument")}
    sel_lane = f1.multiselect("Lane", opts["lane"], format_func=_lane, placeholder="All", key="tb_f_lane")
    sel_grade = f2.multiselect("Grade", opts["grade"], format_func=_grade, placeholder="All", key="tb_f_grade")
    sel_inc = f3.multiselect("Incoterm", opts["incoterm"], placeholder="All", key="tb_f_incoterm")
    sel_px = f4.multiselect("Purchase pricing", opts["purchase_pricing_type"], placeholder="All", key="tb_f_pricing")
    sel_pay = f5.multiselect("Import payment", opts["payment_instrument"], placeholder="All", key="tb_f_payment")
    keep = pd.Series(True, index=book.index)
    for col, chosen in (("lane", sel_lane), ("grade", sel_grade), ("incoterm", sel_inc),
                        ("purchase_pricing_type", sel_px), ("payment_instrument", sel_pay)):
        if chosen:                                   # an empty filter means every value
            keep &= book[col].isin(chosen)
    view = book[keep]
    if view.empty:
        st.info("No ticket matches these filters.", icon=":material/filter_alt_off:")
    else:
        table = pd.DataFrame({
            "Trade": view["trade_id"],
            "Traded": view["trade_date"],
            "Lane": view["lane"].map(_lane),
            "Grade": view["grade"].map(_grade),
            "MT": view["quantity_mt"].map(_f),
            "Boxes": view["boxes"].map(_f),
            "Incoterm": view["incoterm"],
            "Purchase price": view.apply(_buy_price, axis=1),
            "Import payment": [f"{p} {int(_f(u))}d" if _f(u) else p
                               for p, u in zip(view["payment_instrument"], view["usance_days"])],
            "Supplier (SIM)": view["supplier_id"],
            "Buyer(s) (SIM)": view["buyer_ids"],
            "Sale pricing": view["sale_pricing_types"],
            "Sale payment": view["sale_payment_terms"],
            "Sale value ₹ m": view["sale_value_inr"].map(lambda v: (_f(v) or 0) / 1e6),
            "MCX ratio": view["mcx_hedge_ratio_target"].map(_f),
            "FX cover": view["fx_hedge_frac_target"].map(_f),
            "§5a gate": view["trade_eligible"].map({"True": "PASS", "False": "FAIL"}),
            "Last cashflow": view["last_cashflow_date"],
        })
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "MT": st.column_config.NumberColumn(format="localized"),
            "Boxes": st.column_config.NumberColumn(format="%d"),
            "Sale value ₹ m": st.column_config.NumberColumn(format="%.1f"),
            "MCX ratio": st.column_config.NumberColumn(format="%.2f", help="mcx_hedge_ratio_target"),
            "FX cover": st.column_config.NumberColumn(format="%.2f", help="fx_hedge_frac_target"),
        })
        v_mt = sum(_f(v) or 0 for v in view["quantity_mt"])
        st.caption(f"Showing {len(view)} of {n} tickets · {num(v_mt)} MT · "
                   f"{num(sum(_f(v) or 0 for v in view['boxes']))} boxes")
        components.source_caption([BOOK], ["SIM"], note="buy prices are the desk's own bids under its parity (rule S2); "
                                                        "sale prices follow rule S1 — neither is a quote")

    by = book.assign(mt=book["quantity_mt"].map(_f)).groupby(["grade", "lane"], as_index=False)["mt"].sum()
    fig = go.Figure()
    for lane, color in (("JEA_NSA", PALETTE["lme"]), ("USEC_MUN", PALETTE["mcx"])):
        sub = by[by["lane"] == lane]
        fig.add_trace(go.Bar(x=[_grade(g) for g in sub["grade"]], y=sub["mt"], name=_lane(lane), marker_color=color,
                             text=[num(v) for v in sub["mt"]], textposition="outside", cliponaxis=False,
                             hovertemplate="%{x}: %{y:,.0f} MT<extra>" + _lane(lane) + "</extra>"))
    fig.update_layout(barmode="group")
    charts.finish(fig, title="Tonnes by grade and lane", y_title="MT", height=320)
    fig.update_layout(hovermode="closest")
    charts.show(fig, key="tb_mt_by_grade")
    components.source_caption([BOOK], ["SIM"], note="quantity_mt summed by grade and lane")

# ------------------------------------------------------------------------------------------------ ticket card
with tab_card:
    ids = list(book["trade_id"])
    rows = {r["trade_id"]: r for _, r in book.iterrows()}
    tid = st.selectbox("Ticket", ids, format_func=lambda t: _label(rows[t]), key="tb_ticket")
    r = rows[tid]
    tcfg = _ticket_yaml(trades_cfg, tid)
    er = elig[elig["trade_id"] == tid].iloc[0] if elig is not None and (elig["trade_id"] == tid).any() else None

    badges = [components.flag_badge("SIM"), f":blue-badge[{r['status']}]"]
    if er is not None:
        badges.append(f":{'green' if er['status'] == 'PASS' else 'red'}-badge[§5a {er['status']}]")
    st.markdown(f"### {tid} · {_grade(r['grade'])}, {_lane(r['lane'])} &nbsp; " + " ".join(badges))
    st.caption(f"{r['spa_ref']} · {r['supplier_name']} · `{r['sim_label']}`")

    qty, n_box, payload = _f(r["quantity_mt"]) or 0, _f(r["boxes"]) or 0, _f(r["payload_mt_per_box"]) or 0
    components.kpi_row([
        Kpi("Quantity", f"{num(qty)} MT", f"{num(n_box)} × {r['box_type']} at {num(payload, 1)} MT per box, "
                                         f"{r['n_lots']} bill(s) of lading"),
        Kpi("Containers", f"{num(n_box)} × {r['box_type']}"),
        Kpi("Purchase, USD/t" if r["purchase_pricing_type"] == "FIXED" else "Purchase formula",
            num(_f(r["purchase_price_usd_t"]) or 0) if r["purchase_pricing_type"] == "FIXED"
            else f"{_s(r['purchase_factor_frac'])} × LME", _buy_price(r)),
        Kpi("Sold for", inr_m(_f(r["sale_value_inr"]) or 0), "contracted sale value, all parcels"),
        Kpi("Last cashflow", _d(r["last_cashflow_date"]),
            "inside the horizon" if r["settles_inside_horizon"] == "True" else "after the horizon"),
    ])

    with st.container(border=True):
        rat = (tcfg or {}).get("rationale") or {}
        text = rat.get("text") or _s(r.get("rationale"))
        st.markdown(f"**Trader's rationale, {_d(r['trade_date'])}**")
        if text:
            st.markdown(f"> {docs_text.escape_streamlit(' '.join(str(text).split()))}")
            cited = rat.get("cited_columns") or _parts(r.get("rationale_cited_columns"))
            week = rat.get("parity_week_end") or r.get("parity_week_end")
            src = TRADES_YAML if rat.get("text") else BOOK
            components.source_caption(
                [src], ["SIM"], note=f"written against parity week {_d(week)}; cited columns "
                                     f"{', '.join(f'`{c}`' for c in cited)}; numbers in it are reconciled to the panel "
                                     "by desk.book.validate (P08, P13)")
        if trades_cfg is None:
            components.missing_data(TRADES_YAML)

    c_terms, c_ship, c_sales, c_hedge, c_elig, c_events = st.tabs(
        ["Terms (2.2–2.6)", "Shipment & freight (2.8)", "Sales", "Hedge stack (2.7)", "Eligibility (2.9)",
         "Events (SIM)"])

    with c_terms:
        tol = _f(r["quantity_tolerance_frac"])
        lc_tol = _f(r["lc_amount_tolerance_frac"])
        parity_col = "fob_parity_usd_t_at_trade_date" if r["incoterm"] == "FOB" else "cfr_parity_usd_t_at_trade_date"
        if r["purchase_pricing_type"] == "FIXED":
            pricing = (f"FIXED {num(_f(r['purchase_price_usd_t']) or 0, 2)} USD/t {r['incoterm']} against a trade-date "
                       f"{r['incoterm']} parity of {num(_f(r[parity_col]) or 0, 2)} USD/t (grade factor "
                       f"{num(_f(r['grade_factor_at_trade_date']) or 0, 4)})")
        else:
            prov = _f(r["provisional_frac"])
            pricing = (f"{r['purchase_pricing_type']}: {_s(r['purchase_factor_frac'])} × LME official "
                       f"{(_s(r['purchase_lme_reference']) or '').lower()} average over the quotational period "
                       f"{_d(r['pricing_period_start'])} → {_d(r['pricing_period_end'])} (trade-date grade factor "
                       f"{num(_f(r['grade_factor_at_trade_date']) or 0, 4)}); provisional invoice "
                       f"{pct(prov, 0) if prov else '—'} of B/L weight, final invoice {_d(r['final_invoice_date'])}")
        pay = str(r["payment_instrument"])
        if _f(r["usance_days"]):
            pay += f", {int(_f(r['usance_days']))} days from B/L"
        pay += (f"; opened {_d(r['lc_open_date'])} with {r['issuing_bank']}; "
                f"{'confirmed, charges on the ' + str(r['confirmation_charges_for']).lower() if r['lc_confirmed'] == 'True' else 'unconfirmed'}; "
                f"PSIC {'required' if r['psic_required'] == 'True' else 'not required'}")
        paid = _parts(r["usance_maturity_dates"]) or _parts(r["lc_pay_dates"])
        _kv_table([
            ("Grade specification (2.2)", str(r["isri_grade_spec"])),
            ("Quality terms (2.2)",
             f"moisture franchise {pct(_f(r['moisture_franchise_frac']) or 0)}, contamination limit "
             f"{pct(_f(r['contamination_limit_frac']) or 0)}, discount {num(_f(r['discount_multiple']) or 0, 1)}× the "
             f"excess, rejection above +{pct(_f(r['rejection_excess_frac']) or 0)}; radioactivity clause "
             f"`{r['radioactivity_clause_key']}`, penalty schedule `{r['penalty_schedule_key']}`"),
            ("Quantity tolerance (2.1)",
             (f"SPA {pct(tol, 0)}" if tol is not None else "SPA states none")
             + (f"; LC amount tolerance {pct(lc_tol, 0)}" if lc_tol is not None else "")),
            ("Incoterm (2.3)", f"{r['incoterm']} — {r['named_place']}"),
            ("Who books the freight", str(r["freight_booked_by"])),
            ("Cargo risk passes", str(r["cargo_risk_passes"])),
            ("Freight price risk borne by", str(r["freight_risk_borne_by"])),
            ("Purchase pricing (2.4)", pricing),
            ("Import payment (2.6)", pay),
            ("Import paid" if not _parts(r["usance_maturity_dates"]) else "Usance matures",
             ", ".join(_d(p) for p in paid if p)),
            ("Valuation bounds, trade date",
             f"replacement ₹{num(_f(r['replacement_inr_t_at_trade_date']) or 0)}/MT, netback "
             f"₹{num(_f(r['netback_inr_t_at_trade_date']) or 0)}/MT, landed ₹{num(_f(r['landed_inr_t_at_trade_date']) or 0)}/MT"),
        ])
        components.source_caption([BOOK], {"counterparties, bank, SPA": "SIM",
                                           "grade factor (lag-2 reconstruction)":
                                               data.param_flag("grade_factor_mix") or "ASSUMPTION",
                                           "USD/INR": flags.get("usdinr", "PROXY")})
        note = (((tcfg or {}).get("purchase") or {}).get("pricing") or {}).get("terms_basis_note")
        if note:
            with st.expander("Purchase pricing note, as typed on the ticket"):
                st.markdown(docs_text.escape_streamlit(" ".join(str(note).split())))
                st.caption(f"Source: `{TRADES_YAML}` (`purchase.pricing.terms_basis_note`).")

    with c_ship:
        st.markdown(f"**Laycan** {_d(r['laycan_start'])} → {_d(r['laycan_end'])}, {r['load_port']} → "
                    f"{r['discharge_port']} " + components.flag_badge("SIM") + " vessels and voyages")
        lots = _parts(r["lot_ids"])
        lot_df = pd.DataFrame({
            "Lot": lots,
            "Boxes": [_f(x) for x in _parts(r["lot_boxes"])],
            "B/L": _parts(r["bl_dates"]),
            "Vessel (SIM)": _parts(r["vessels"]),
            "Voyage (SIM)": _parts(r["voyages"]),
            "Arrival": _parts(r["arrival_dates"]),
            "Bill of Entry": _parts(r["boe_dates"]),
            "Released": _parts(r["release_dates"]),
            "IGST credit": _parts(r["igst_credit_dates"]),
            "Import paid / matures": [_at(_parts(r["usance_maturity_dates"]) or _parts(r["lc_pay_dates"]), i)
                                      for i in range(len(lots))],
            "Chargeable dwell days": [_f(x) for x in _parts(r["chargeable_dwell_days"])],
        })
        st.dataframe(lot_df, hide_index=True, width="stretch",
                     column_config={"Boxes": st.column_config.NumberColumn(format="%d"),
                                    "Chargeable dwell days": st.column_config.NumberColumn(format="%d")})
        components.source_caption([BOOK], ["SIM"], note="arrival, clearance and payment dates are derived by the engine "
                                                        "from the typed B/L dates (transit and clearance days: ASSUMPTION)")

        st.markdown("**Freight: fixture against the lane index**")
        rate = _f(r["freight_rate_usd_box"])
        freight_flag = flags.get(FREIGHT_COL.get(str(r["lane"]), ""), "ASSUMPTION")
        if rate is None:
            st.info(f"{r['incoterm']}: ocean freight is booked by {r['freight_booked_by']}. The CFR grade factor does not "
                    "move when the lane does, so this cargo carries no freight price risk for the desk — only the "
                    "seller's schedule risk.", icon=":material/directions_boat:")
            components.source_caption([BOOK], {"freight levels": freight_flag})
        else:
            idx = _f(r["freight_index_usd_box_at_fixture"]) or 0
            stop = _f(r["freight_stop_loss_usd_box"])
            components.kpi_row([
                Kpi("Fixture, USD/box", num(rate), f"fixed {_d(r['freight_fixture_date'])} with {r['freight_forwarder']}"),
                Kpi("Index, USD/box", num(idx, 2), f"reconstructed lane index at the fixture date ({freight_flag})"),
                Kpi("Fixture vs index", pct(rate / idx - 1, 2, sign=True) if idx else "n/a"),
                Kpi("Stop, USD/box", num(stop) if stop else "—", f"book-by date {_d(r['freight_latest_fixture_date'])}"),
                Kpi("Freight, USD", num(_f(r["freight_total_usd"]) or 0), str(r["freight_payment_terms"])),
            ])
            fig = go.Figure(go.Bar(
                x=["Lane index at fixture", "Fixture", "Stop-loss"], y=[idx, rate, stop or 0],
                marker_color=[PALETTE["neutral"], PALETTE["freight"], PALETTE["loss"]],
                text=[f"{num(v)}" for v in (idx, rate, stop or 0)], textposition="outside", cliponaxis=False,
                hovertemplate="%{x}: %{y:,.0f} USD/box<extra></extra>"))
            charts.finish(fig, y_title="USD per box", height=280, legend=False)
            fig.update_layout(hovermode="closest")
            fig.update_yaxes(range=[0, 1.18 * max(idx, rate, stop or 0)])
            charts.show(fig, key=f"tb_freight_{tid}")
            components.source_caption([BOOK, HEDGES], {"lane index and levels": freight_flag, "forwarder": "SIM"},
                                      note=f"risk layer {r['freight_risk_layer']}: no India-lane container derivative was "
                                           "accessible in 2022, so freight is a written policy, not a hedge")
            sl_note = (((tcfg or {}).get("freight") or {}).get("stop_loss") or {}).get("note")
            if sl_note:
                with st.expander("Stop-loss note, as typed on the ticket"):
                    st.markdown(docs_text.escape_streamlit(" ".join(str(sl_note).split())))
                    st.caption(f"Source: `{TRADES_YAML}` (`freight.stop_loss.note`).")

    with c_sales:
        sids = _parts(r["sale_ids"])
        pricing_types = _parts(r["sale_pricing_types"])
        prices, windows = _parts(r["sale_price_inr_t"]), _parts(r["sale_pricing_window"])
        factors, premia = _parts(r["sale_factor_frac"]), _parts(r["sale_premium_inr_t"])
        series = _parts(r["sale_mcx_series"])
        credit_days, adv = _parts(r["sale_credit_days"]), _parts(r["sale_advance_frac"])
        sale_rows = []
        for i, sid in enumerate(sids):
            if _at(pricing_types, i) == "FIXED":
                px = f"FIXED ₹{_at(prices, i)}/MT"
            else:
                w = (_at(windows, i) or "").split("..")
                px = (f"{_at(factors, i)} × MCX {_at(series, i)} average "
                      + (f"{_d(w[0], False)}–{_d(w[1])}" if len(w) == 2 else "") + f", premium ₹{_at(premia, i)}/MT")
            a = _f(_at(adv, i))
            terms = str(_at(_parts(r["sale_payment_terms"]), i))
            if a:
                terms += f"; {pct(a, 0)} advance on {_d(_at(_parts(r['sale_advance_dates']), i))}"
            if _at(credit_days, i):
                terms += f"; {_at(credit_days, i)}-day credit"
            sale_rows.append({
                "Sale": sid, "Buyer (SIM)": _at(_parts(r["buyer_names"]), i), "Contracted": _at(_parts(r["sale_contract_dates"]), i),
                "Lots": _at(_parts(r["sale_lot_ids"]), i), "Delivery": _at(_parts(r["sale_delivery_basis"]), i),
                "Pricing": px, "Payment terms (2.6)": terms, "Invoice": _at(_parts(r["sale_invoice_dates"]), i),
                "Due (contract)": _at(_parts(r["sale_due_dates_contractual"]), i),
                "Due (with SIM events)": _at(_parts(r["sale_due_dates_with_events"]), i),
                "Quality pass-through": _at(_parts(r["quality_passthrough"]), i),
            })
        st.dataframe(pd.DataFrame(sale_rows), hide_index=True, width="stretch")
        st.caption(f"Bounds at the first sale: replacement ₹{num(_f(r['replacement_inr_t_at_first_sale']) or 0)}/MT, "
                   f"netback ₹{num(_f(r['netback_inr_t_at_first_sale']) or 0)}/MT. Rule S1 prices the sale at "
                   "replacement + 50 % of the gap, adjusted for payment terms at the desk's own cost of money.")
        components.source_caption([BOOK], {"buyers": "SIM",
                                           "netback anchor premium": data.param_flag("domestic_anchor_premium_inr_t")
                                           or "ASSUMPTION"})
        notes = [(s.get("sale_id"), ((s.get("pricing") or {}).get("terms_basis_note")))
                 for s in (tcfg or {}).get("sales", [])]
        if any(nt for _, nt in notes):
            with st.expander("Sale pricing notes, as typed on the ticket"):
                for sid, nt in notes:
                    if nt:
                        st.markdown(f"**{sid}.** " + docs_text.escape_streamlit(" ".join(str(nt).split())))
                st.caption(f"Source: `{TRADES_YAML}` (`sales[].pricing.terms_basis_note`).")

    with c_hedge:
        hedges = data.trade_hedges()
        if hedges is None:
            components.missing_data(HEDGES)
        else:
            h = hedges[hedges["trade_id"] == tid]
            mcx = h[h["instrument"] == "MCX_ALUMINIUM_FUTURE"]
            fx = h[h["instrument"] == "USDINR_FORWARD"]
            components.kpi_row([
                Kpi("MCX ratio target", num(_f(r["mcx_hedge_ratio_target"]) or 0, 2), "of the net LME-equivalent delta (H1–H2)"),
                Kpi("MCX tranches · rolls", f"{r['mcx_tranches']} · {r['mcx_rolls']}"),
                Kpi("Lots at first entry", str(r["mcx_lots_at_first_entry"]), "5 MT per lot"),
                Kpi("FX cover target", num(_f(r["fx_hedge_frac_target"]) or 0, 2), "of the contracted USD payable (H6)"),
                Kpi("FX forwards", f"{r['fx_forward_lines']} lines", f"gross USD {num(_f(r['fx_gross_notional_usd']) or 0)}"),
            ])
            st.markdown("**MCX Aluminium futures** — entry, roll and exit")
            st.dataframe(mcx[["hedge_id", "decision_date", "contract_month", "direction", "lots", "position_mt",
                              "entry_date", "entry_price_inr_kg", "exit_date", "exit_price_inr_kg", "exit_reason",
                              "roll_to", "roll_deadline", "im_required_at_entry_inr", "hedge_ratio_actual",
                              "sizing_basis"]],
                         hide_index=True, width="stretch", column_config={
                             "lots": st.column_config.NumberColumn(format="%d"),
                             "position_mt": st.column_config.NumberColumn(format="%d"),
                             "im_required_at_entry_inr": st.column_config.NumberColumn("IM at entry ₹", format="localized"),
                             "entry_price_inr_kg": st.column_config.NumberColumn("entry ₹/kg", format="%.2f"),
                             "exit_price_inr_kg": st.column_config.NumberColumn("exit ₹/kg", format="%.2f"),
                             "hedge_ratio_actual": st.column_config.NumberColumn(format="%.3f")})
            components.source_caption([HEDGES], {"MCX prices (duty-paid parity series)": flags.get("mcx_al_m1_inr_kg", "PROXY")},
                                      note="fills and settlements are the panel proxy, not MCX prints; the proxy is in "
                                           "contango by construction, so every roll of a short shows a gain")
            st.markdown("**USD/INR forwards**")
            st.dataframe(fx[["hedge_id", "booking_date", "direction", "notional_usd", "value_date", "cancel_date",
                             "matched_leg", "forward_mid_inr", "bank_margin_inr", "rate_inr", "exit_reason"]],
                         hide_index=True, width="stretch", column_config={
                             "notional_usd": st.column_config.NumberColumn("notional USD", format="localized"),
                             "forward_mid_inr": st.column_config.NumberColumn("forward mid", format="%.4f"),
                             "rate_inr": st.column_config.NumberColumn("dealt rate", format="%.4f")})
            components.source_caption([HEDGES], {"USD/INR and forward points": flags.get("usdinr", "PROXY")},
                                      note="dealt on the bill of lading, when both the amount and the payment date exist")
            basis = next((x for x in h["basis_risk_note"].dropna()), None)
            if basis:
                with st.expander("Basis-risk note on this hedge (2.7c)"):
                    st.markdown(docs_text.escape_streamlit(str(basis)))
                    st.caption(f"Source: `{HEDGES}` (`basis_risk_note`, as typed in `{TRADES_YAML}`).")

    with c_elig:
        if er is None:
            components.missing_data(ELIG) if elig is None else st.info("No eligibility row for this ticket.")
        else:
            screens = [("Base screen", "net_arb_inr_t", "open_base"), ("Point-in-time grade mix", "net_arb_pit_mix_inr_t",
                                                                        "open_pit_mix"),
                       ("Conversion at ₹18,000/t", "net_arb_conv18k_inr_t", "open_conv18k")]
            thr = float(er["margin_threshold_inr_t"])
            fig = go.Figure(go.Bar(
                x=[s[0] for s in screens], y=[float(er[s[1]]) for s in screens],
                marker_color=[PALETTE["gain"] if bool(er[s[2]]) else PALETTE["loss"] for s in screens],
                text=[f"₹{num(float(er[s[1]]))}" for s in screens], textposition="outside", cliponaxis=False,
                hovertemplate="%{x}: ₹%{y:,.0f}/MT<extra></extra>"))
            fig.add_hline(y=thr, line_dash="dash", line_color=PALETTE["loss"],
                          annotation_text=f"margin threshold ₹{num(thr)}/MT", annotation_position="top left")
            charts.finish(fig, title=f"Net arbitrage in parity week {_d(er['parity_week_end_used'])}", y_title="₹ per MT",
                          height=320, legend=False)
            fig.update_layout(hovermode="closest")
            charts.show(fig, key=f"tb_elig_{tid}")
            st.markdown(
                f"Gate **{er['status']}** — open on the base screen: **{er['open_base']}**, point-in-time mix: "
                f"**{er['open_pit_mix']}**, conversion stressed: **{er['open_conv18k']}**. On the trade date itself: LME "
                f"3M {num(float(er['trade_date_lme_3m_usd_t']), 1)} USD/t, grade factor "
                f"{num(float(er['trade_date_grade_factor']), 4)}, net arb ₹{num(float(er['trade_date_net_arb_inr_t']))}/MT.")
            components.source_caption([ELIG], {"grade factors (the base and stressed screens)":
                                               data.param_flag("grade_factor_mix") or "ASSUMPTION",
                                               "LME 3M": flags.get("lme_3m_usd_t", "DIRECT")},
                                      note="a trade dated d is tested against the latest parity week ending on or before d")

    with c_events:
        ev = (tcfg or {}).get("events") or {}
        if not ev and not any(_s(r[c]) for c in ("event_quality", "event_logistics", "event_buyer_payment_delay")):
            st.info("No simulated operational event on this ticket.", icon=":material/check_circle:")
        elif ev:
            st.markdown(components.flag_badge("SIM") + " Every magnitude below is simulated; where a real, dated "
                                                        "trigger is cited, only the trigger is real.")
            for q in ev.get("quality", []):
                with st.container(border=True):
                    st.markdown(
                        f"**Quality out-turn, lot {q.get('lot_id')}** {components.flag_badge(q.get('flag', 'SIM'))} — "
                        f"moisture {pct(q.get('moisture_actual_frac', 0))} against the "
                        f"{pct(_f(r['moisture_franchise_frac']) or 0)} franchise, contamination "
                        f"{pct(q.get('contamination_actual_frac', 0))} against the "
                        f"{pct(_f(r['contamination_limit_frac']) or 0)} limit, {q.get('rejected_boxes', 0)} box(es) "
                        f"rejected{' (' + q['rejection_reason'] + ')' if q.get('rejection_reason') else ''}; claim "
                        f"recovery {pct(q.get('claim_recovery_frac', 0), 0)}")
                    if q.get("note"):
                        st.caption(docs_text.escape_streamlit(" ".join(str(q["note"]).split())))
            for lg in ev.get("logistics", []):
                with st.container(border=True):
                    st.markdown(
                        f"**{lg.get('event_id')} — lot {lg.get('lot_id')}** {components.flag_badge(lg.get('flag', 'SIM'))}"
                        f" known {_d(lg.get('known_date'))}: +{lg.get('arrival_delay_days', 0)} days arrival, "
                        f"+{lg.get('extra_dwell_days', 0)} days CFS dwell")
                    if lg.get("real_trigger_ref"):
                        st.caption("Real trigger: " + docs_text.escape_streamlit(" ".join(str(lg["real_trigger_ref"]).split())))
                    if lg.get("note"):
                        st.caption(docs_text.escape_streamlit(" ".join(str(lg["note"]).split())))
            for pdly in ev.get("buyer_payment_delay", []):
                with st.container(border=True):
                    st.markdown(
                        f"**{pdly.get('event_id')} — buyer payment delay on {pdly.get('sale_id')}** "
                        f"{components.flag_badge(pdly.get('flag', 'SIM'))} known {_d(pdly.get('known_date'))}: "
                        f"+{pdly.get('delay_days')} days past due")
                    if pdly.get("reason"):
                        st.caption(docs_text.escape_streamlit(" ".join(str(pdly["reason"]).split())))
            dem, dem_t = _f(r["demurrage_usd_at_plan"]) or 0, _f(r["demurrage_usd_at_plan_tiered"]) or 0
            st.caption(f"Detention at plan: USD {num(dem)} at the first-slab rate, USD {num(dem_t)} charged up the "
                       f"registered slabs; chargeable dwell days by lot: {r['chargeable_dwell_days']}.")
            components.source_caption([TRADES_YAML, BOOK], ["SIM"])
        else:
            if trades_cfg is None:
                components.missing_data(TRADES_YAML)
            for c in ("event_quality", "event_logistics", "event_buyer_payment_delay"):
                for p in _parts(r[c]):
                    st.markdown(f"- {components.flag_badge('SIM')} {docs_text.escape_streamlit(p)}")
            components.source_caption([BOOK], ["SIM"])

# ------------------------------------------------------------------------------------------------ timeline
PHASE_COLORS = {
    "Laycan": PALETTE["neutral"],
    "Purchase quotational period": PALETTE["lme"],
    "Sailing: first B/L → last arrival": PALETTE["freight"],
    "Sale pricing window (MCX average)": PALETTE["mcx"],
    "Receivables: first invoice → last due": PALETTE["fx"],
}
MARKERS = {"Trade date": ("diamond", "#262730"), "LC opened": ("circle-open", PALETTE["lme"]),
           "Sale contracted": ("triangle-up", PALETTE["mcx"]), "Last cashflow (settled)": ("square", PALETTE["gain"])}


def _gantt_rows(row: pd.Series) -> tuple[list[dict], list[dict]]:
    tid = row["trade_id"]
    bars, pts = [], []

    def bar(phase: str, a: str | None, b: str | None) -> None:
        if a and b:
            bars.append({"trade": tid, "phase": phase, "start": pd.Timestamp(a), "end": pd.Timestamp(b)})

    def pt(kind: str, when: str | None) -> None:
        if when:
            pts.append({"trade": tid, "kind": kind, "date": pd.Timestamp(when)})

    bar("Laycan", _s(row["laycan_start"]), _s(row["laycan_end"]))
    bar("Purchase quotational period", _s(row["pricing_period_start"]), _s(row["pricing_period_end"]))
    bls, arr = [x for x in _parts(row["bl_dates"]) if x], [x for x in _parts(row["arrival_dates"]) if x]
    if bls and arr:
        bar("Sailing: first B/L → last arrival", min(bls), max(arr))
    for w in _parts(row["sale_pricing_window"]):
        if ".." in w:
            a, b = w.split("..")
            bar("Sale pricing window (MCX average)", a, b)
    inv, due = [x for x in _parts(row["sale_invoice_dates"]) if x], [x for x in _parts(row["sale_due_dates_with_events"]) if x]
    if inv and due:
        bar("Receivables: first invoice → last due", min(inv), max(due))
    pt("Trade date", _s(row["trade_date"]))
    pt("LC opened", _s(row["lc_open_date"]))
    for c in _parts(row["sale_contract_dates"]):
        pt("Sale contracted", c or None)
    pt("Last cashflow (settled)", _s(row["last_cashflow_date"]))
    return bars, pts


with tab_time:
    st.subheader("Every ticket's life, trade date to settlement")
    chosen = st.multiselect("Tickets", list(book["trade_id"]), default=list(book["trade_id"]), key="tb_gantt_trades")
    if not chosen:
        st.info("Pick at least one ticket.", icon=":material/filter_alt_off:")
    else:
        bars, pts = [], []
        for _, row in book[book["trade_id"].isin(chosen)].iterrows():
            b, p = _gantt_rows(row)
            bars += b
            pts += p
        order = sorted(chosen)
        fig = go.Figure()
        bdf = pd.DataFrame(bars)
        for phase, color in PHASE_COLORS.items():
            sub = bdf[bdf["phase"] == phase] if not bdf.empty else bdf
            if sub.empty:
                continue
            fig.add_trace(go.Bar(
                y=sub["trade"], x=(sub["end"] - sub["start"]).dt.total_seconds() * 1000 + 86_400_000,
                base=sub["start"].dt.strftime("%Y-%m-%d"), orientation="h", name=phase, marker_color=color,
                offsetgroup=phase, opacity=0.85,
                customdata=list(zip(sub["start"].dt.strftime("%-d-%b"), sub["end"].dt.strftime("%-d-%b-%Y"))),
                hovertemplate="%{y} · " + phase + ": %{customdata[0]} → %{customdata[1]}<extra></extra>"))
        pdf = pd.DataFrame(pts)
        for kind, (symbol, color) in MARKERS.items():
            sub = pdf[pdf["kind"] == kind]
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub["trade"], mode="markers", name=kind,
                marker=dict(symbol=symbol, size=10, color=color, line=dict(width=1, color="white")),
                customdata=sub["date"].dt.strftime("%-d-%b-%Y"),
                hovertemplate="%{y} · " + kind + ": %{customdata}<extra></extra>"))
        fig.update_layout(barmode="group", bargap=0.2, bargroupgap=0.0)
        charts.shade_window(fig)
        charts.mark_events(fig, [(WINDOW_END, "window end"), (HORIZON_END, "horizon")], color=charts.MUTED)
        charts.finish(fig, height=max(320, 70 * len(order) + 140))
        fig.update_yaxes(type="category", categoryorder="array", categoryarray=order, autorange="reversed")
        fig.update_xaxes(type="date")
        fig.update_layout(hovermode="closest", margin=dict(t=30, b=130),
                          legend=dict(orientation="h", yref="container", yanchor="bottom", y=0.005, x=0, xanchor="left"))
        charts.show(fig, key="tb_gantt")
        components.source_caption([BOOK], ["SIM"],
                                  note="laycans, B/L and sale dates are typed on the tickets; quotational periods, arrival, "
                                       "invoice, due and settlement dates are derived by the engine; SIM events move "
                                       "some of them (T07, T08)")

# ------------------------------------------------------------------------------------------------ counterparties
with tab_cp:
    st.subheader("Counterparties and credit limits (2.5)")
    cps = data.counterparties_yaml()
    if cps is None:
        components.missing_data(CPS_YAML)
    else:
        tickets = {}
        for _, row in book.iterrows():
            tickets.setdefault(row["supplier_id"], []).append(row["trade_id"])
            for b in dict.fromkeys(_parts(row["buyer_ids"])):
                tickets.setdefault(b, []).append(row["trade_id"])
        recs = []
        for c in cps.get("counterparties", []):
            prof = c.get("profile") or {}
            buyer = c.get("role") == "BUYER"
            recs.append({
                "Id": c.get("cp_id"), "Name (SIM)": c.get("name"), "Role": c.get("role"), "Type": c.get("type"),
                "Location (SIM)": c.get("location"), "Lanes": ", ".join(c.get("lanes", [])),
                "Limit": (f"₹{num(c['credit_limit_inr'] / 1e6)} m credit" if buyer and c.get("credit_limit_inr")
                          else f"USD {num(c.get('claims_exposure_limit_usd', 0))} claims"),
                "Terms": (f"{c.get('default_payment_terms')}, {c.get('credit_days_default')}d" if buyer else
                          ("LC confirmed" if c.get("lc_confirmation_required") else "LC unconfirmed")),
                "Rating (SIM)": prof.get("internal_rating_sim"),
                "Since": str(prof.get("relationship_start", "")),
                "Tickets": ", ".join(tickets.get(c.get("cp_id"), [])),
            })
        st.dataframe(pd.DataFrame(recs), hide_index=True, width="stretch")
        components.source_caption([CPS_YAML, BOOK], ["SIM"],
                                  note="limits are the desk's own policy, stated before the book was priced")

    credit = data.trade_credit_exposure()
    if credit is None:
        components.missing_data(CREDIT)
    else:
        st.markdown("**Credit exposure at each sale booking** — the number rule P04 checks")
        buyers = ["All buyers", *sorted(credit["buyer_id"].unique())]
        who = st.selectbox("Buyer", buyers, key="tb_credit_buyer")
        cv = credit if who == "All buyers" else credit[credit["buyer_id"] == who]
        fig = go.Figure(go.Bar(
            x=[f"{d} · {t}-{s}" for d, t, s in zip(cv["contract_date"], cv["trade_id"], cv["sale_id"])],
            y=cv["utilisation_frac"] * 100,
            marker_color=[PALETTE["loss"] if u > 0.9 else PALETTE["mcx"] if u > 0.75 else PALETTE["lme"]
                          for u in cv["utilisation_frac"]],
            text=[pct(u, 0) for u in cv["utilisation_frac"]], textposition="outside", cliponaxis=False,
            customdata=cv["buyer_id"], hovertemplate="%{x} · %{customdata}: %{y:.0f} % of the line<extra></extra>"))
        fig.add_hline(y=100, line_dash="dash", line_color=PALETTE["loss"], annotation_text="credit limit",
                      annotation_position="top left")
        charts.finish(fig, y_title="% of the buyer's credit limit", height=340, legend=False)
        fig.update_layout(hovermode="closest")
        fig.update_xaxes(tickangle=-30)
        charts.show(fig, key="tb_credit_util")
        money_cols = ["price_inr_t", "invoice_value_inr", "credit_value_inr", "exposure_after_inr", "credit_limit_inr"]
        shown = cv.assign(**{c: cv[c].round(0) for c in money_cols}, utilisation_frac=cv["utilisation_frac"] * 100)
        st.dataframe(shown[["contract_date", "trade_id", "sale_id", "buyer_id", "qty_mt", *money_cols, "utilisation_frac",
                            "within_limit"]],
                     hide_index=True, width="stretch", column_config={
                         "price_inr_t": st.column_config.NumberColumn("₹/MT", format="localized"),
                         "invoice_value_inr": st.column_config.NumberColumn("invoice ₹", format="localized"),
                         "credit_value_inr": st.column_config.NumberColumn("on credit ₹", format="localized"),
                         "exposure_after_inr": st.column_config.NumberColumn("exposure after ₹", format="localized"),
                         "credit_limit_inr": st.column_config.NumberColumn("limit ₹", format="localized"),
                         "qty_mt": st.column_config.NumberColumn("MT", format="localized"),
                         "utilisation_frac": st.column_config.NumberColumn("use %", format="%.0f")})
        components.source_caption([CREDIT], ["SIM"],
                                  note="receivable + the not-advance-covered part of contracted sales, at each booking "
                                       "(bars: blue under 75 %, orange 75–90 %, red over 90 %). "
                                       "An advance is not credit, so this table cannot see the advances the book relies "
                                       "on (docs/20 §2, rule P14); the daily receivable measure is on the P&L page, event 3")

# ------------------------------------------------------------------------------------------------ eligibility
with tab_elig:
    st.subheader("Trade discipline: the parity window each ticket was traded in (2.9)")
    if elig is None:
        components.missing_data(ELIG)
    else:
        e = elig.sort_values("trade_id")
        fig = go.Figure()
        for label, col, color in (("Base", "net_arb_inr_t", PALETTE["lme"]),
                                  ("Point-in-time mix", "net_arb_pit_mix_inr_t", PALETTE["fx"]),
                                  ("Conversion ₹18k", "net_arb_conv18k_inr_t", PALETTE["mcx"])):
            fig.add_trace(go.Bar(x=e["trade_id"], y=e[col], name=label, marker_color=color,
                                 hovertemplate="%{x}: ₹%{y:,.0f}/MT<extra>" + label + "</extra>"))
        thr = float(e["margin_threshold_inr_t"].iloc[0])
        fig.add_hline(y=thr, line_dash="dash", line_color=PALETTE["loss"],
                      annotation_text=f"threshold ₹{num(thr)}/MT", annotation_position="top right")
        fig.update_layout(barmode="group")
        charts.finish(fig, y_title="net arbitrage, ₹ per MT", height=380)
        fig.update_layout(hovermode="closest")
        charts.show(fig, key="tb_elig_all")
        st.dataframe(e[["trade_id", "trade_date", "grade", "lane", "parity_week_end_used", "open_base", "open_pit_mix",
                        "open_conv18k", "net_arb_inr_t", "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t",
                        "margin_threshold_inr_t", "week_matches_ticket", "status"]],
                     hide_index=True, width="stretch", column_config={
                         c: st.column_config.NumberColumn(format="localized")
                         for c in ("net_arb_inr_t", "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t",
                                   "margin_threshold_inr_t")})
        components.source_caption([ELIG, TRADES_YAML], {"grade factors": data.param_flag("grade_factor_mix") or "ASSUMPTION",
                                                        "anchor premium in the netback":
                                                            data.param_flag("domestic_anchor_premium_inr_t") or "ASSUMPTION"},
                                  note="the rule (CONTRACTS §5a) was declared before any parity result existed")
    sec = docs_text.section(DOC, "Trade discipline")
    if sec is not None:
        with st.expander("Why the three screens are not independent (docs/20 §3)", icon=":material/menu_book:"):
            st.markdown(docs_text.for_streamlit(sec.body, DOC))
            st.caption(f"Quoted from `{DOC}` §{sec.number}, not rewritten for the app.")

# ------------------------------------------------------------------------------------------------ docs
st.subheader("Read with")
components.what_it_tells(DOC, heading="Changes during review")
components.what_it_tells(DOC)
