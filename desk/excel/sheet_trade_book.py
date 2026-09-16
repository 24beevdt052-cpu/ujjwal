"""`Trade_Book` — the nine SPA tickets (MASTER_SPEC Table 4), as inputs, with the §5a discipline re-checked live.

Ticket fields are inputs because that is what they are: an executed decision — grade, lane, tonnage, incoterm,
pricing formula, payment terms, laycan, hedge stack, the rate actually fixed. CONTRACTS §7a.2 forbids a ticket from
carrying a derived number, so no fill price, invoice value or cashflow date is typed here; those are recomputed and
live on `Cashflows` and `MTM_Daily`.

Three columns *are* formulas, and they are the point of the sheet:

* `parity_net_arb_inr_t`, `parity_net_arb_pit_inr_t` and `parity_eligible_live` look the ticket's
  `parity_week_end × grade × lane` up on the `Parity` sheet with `SUMIFS`. Change a parameter on `Inputs` hard
  enough and a ticket that was eligible stops being eligible — the discipline rule (CONTRACTS §5a, Table 4 row 2.9)
  is re-tested in the workbook rather than asserted in prose.
* `eligible_matches_book` compares that live answer to the flag Phase 2 recorded, so a silent drift is visible.

The trader's rationale is on the sheet in full: a trade dated `d` may use only information published on or before
`d`, and the rationale is where that is argued.
"""

from __future__ import annotations

import pandas as pd

from desk.excel import sources
from desk.excel.layout import INPUT, KEY, PASTED, Column, Sheet

SHEET = "Trade_Book"

# Ticket fields shown, in desk-reading order. Every one is an input typed from config/trades.yaml via trade_book.csv.
FIELDS = [
    ("trade_id", KEY, 9), ("status", KEY, 11), ("trade_date", KEY, 12), ("in_window", KEY, 10),
    ("lane", KEY, 11), ("grade", KEY, 12), ("isri_grade_spec", INPUT, 34),
    ("quantity_mt", INPUT, 12), ("boxes", INPUT, 8), ("box_type", INPUT, 9), ("payload_mt_per_box", INPUT, 10),
    ("n_lots", INPUT, 8), ("parity_week_end", KEY, 13),
    ("supplier_id", INPUT, 14), ("supplier_name", INPUT, 34), ("spa_ref", INPUT, 22),
    ("incoterm", INPUT, 10), ("named_place", INPUT, 26), ("freight_booked_by", INPUT, 14),
    ("freight_risk_borne_by", INPUT, 14),
    ("moisture_franchise_frac", INPUT, 12), ("contamination_limit_frac", INPUT, 12),
    ("discount_multiple", INPUT, 10), ("rejection_excess_frac", INPUT, 11),
    ("quantity_tolerance_frac", INPUT, 11),
    ("purchase_pricing_type", INPUT, 14), ("purchase_price_usd_t", INPUT, 13),
    ("purchase_lme_reference", INPUT, 13), ("purchase_factor_frac", INPUT, 12),
    ("purchase_premium_usd_t", INPUT, 12), ("provisional_frac", INPUT, 11),
    ("pricing_period_month", INPUT, 12), ("pricing_period_start", INPUT, 13), ("pricing_period_end", INPUT, 13),
    ("payment_instrument", INPUT, 13), ("usance_days", INPUT, 10), ("lc_open_date", INPUT, 12),
    ("issuing_bank", INPUT, 28), ("lc_confirmed", INPUT, 10), ("confirmation_charges_for", INPUT, 13),
    ("psic_required", INPUT, 11),
    ("laycan_start", INPUT, 12), ("laycan_end", INPUT, 12), ("load_port", INPUT, 20),
    ("discharge_port", INPUT, 14), ("lot_ids", INPUT, 14), ("lot_boxes", INPUT, 14),
    ("bl_dates", INPUT, 30), ("vessels", INPUT, 60), ("voyages", INPUT, 26),
    ("freight_forwarder", INPUT, 26), ("freight_payment_terms", INPUT, 16),
    ("freight_risk_layer", INPUT, 18), ("freight_fixture_date", INPUT, 12),
    ("freight_rate_usd_box", INPUT, 12), ("freight_index_usd_box_at_fixture", INPUT, 13),
    ("freight_stop_loss_usd_box", INPUT, 12), ("freight_total_usd", INPUT, 13),
    ("sale_ids", INPUT, 12), ("buyer_ids", INPUT, 22), ("buyer_names", INPUT, 50),
    ("sale_contract_dates", INPUT, 22), ("sale_lot_ids", INPUT, 14), ("sale_delivery_basis", INPUT, 40),
    ("sale_pricing_types", INPUT, 14), ("sale_price_inr_t", INPUT, 20), ("sale_mcx_series", INPUT, 12),
    ("sale_pricing_window", INPUT, 22), ("sale_factor_frac", INPUT, 12), ("sale_premium_inr_t", INPUT, 12),
    ("sale_payment_terms", INPUT, 22), ("sale_credit_days", INPUT, 11), ("sale_advance_frac", INPUT, 11),
    ("sale_value_inr", INPUT, 16), ("quality_passthrough", INPUT, 12),
    ("mcx_hedge_ratio_target", INPUT, 12), ("mcx_tranches", INPUT, 10), ("mcx_rolls", INPUT, 9),
    ("mcx_lots_at_first_entry", INPUT, 12), ("fx_hedge_frac_target", INPUT, 12),
    ("fx_forward_lines", INPUT, 11), ("fx_gross_notional_usd", INPUT, 16),
    ("purchase_usd_at_contract", INPUT, 16), ("fx_cover_frac_of_fixed_purchase", INPUT, 13),
    ("event_quality", INPUT, 26), ("event_logistics", INPUT, 26), ("event_buyer_payment_delay", INPUT, 26),
    ("last_cashflow_date", INPUT, 13), ("close_date", INPUT, 12), ("settles_inside_horizon", INPUT, 11),
]
PASTED_FIELDS = [("net_arb_inr_t", 14), ("net_arb_pit_mix_inr_t", 14), ("trade_eligible", 12),
                 ("replacement_inr_t_at_trade_date", 16), ("netback_inr_t_at_trade_date", 16),
                 ("p1_finance_memo_inr", 16)]
LIVE = ["parity_net_arb_inr_t", "parity_net_arb_pit_inr_t", "parity_net_arb_conv18k_inr_t", "parity_eligible_live",
        "eligible_matches_book"]


def write(wb, counts, data: sources.Data, parity_t):
    sh = Sheet(wb, SHEET, "Trade_Book — nine SPA tickets (MASTER_SPEC Table 4). Every counterparty and vessel is SIM",
               counts,
               subtitle="Source: config/trades.yaml, as Phase 2 publishes it in outputs/tables/trade_book.csv. "
                        "Blue = ticket input (an executed decision). Green = the Phase 2 value, kept so the live "
                        "parity look-up beside it can be checked. Black = live CONTRACTS §5a discipline check.")
    cols = [Column(n, k, width=w) for n, k, w in FIELDS]
    cols += [Column(f"book_{n}", PASTED, width=w) for n, w in PASTED_FIELDS]
    cols += [Column(c, width=15) for c in LIVE]
    cols += [Column("rationale", KEY, width=120), Column("rationale_cited_columns", KEY, width=48),
             Column("sim_label", KEY, width=36)]
    t = sh.table(cols)

    tb = data.trade_book
    for i, row in enumerate(tb.itertuples(index=False)):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        r = {}
        for name, _kind, _w in FIELDS:
            v = getattr(row, name, None)
            r[name] = _cell(v)
        for name, _w in PASTED_FIELDS:
            r[f"book_{name}"] = _cell(getattr(row, name, None))
        sif = (lambda col: f"SUMIFS({parity_t.abs(col)},{parity_t.abs('week_end')},{R('parity_week_end')},"
                           f"{parity_t.abs('grade')},{R('grade')},{parity_t.abs('lane')},{R('lane')})")
        r["parity_net_arb_inr_t"] = "=" + sif("net_arb_inr_t")
        r["parity_net_arb_pit_inr_t"] = "=" + sif("net_arb_pit_mix_inr_t")
        r["parity_net_arb_conv18k_inr_t"] = "=" + sif("net_arb_conv18k_inr_t")
        r["parity_eligible_live"] = "=" + sif("trade_eligible_n") + ">0"
        r["eligible_matches_book"] = (f'=IF({R("parity_eligible_live")}={R("book_trade_eligible")},'
                                      f'"PASS","FAIL")')
        r["rationale"] = " ".join(str(getattr(row, "rationale", "")).split())
        r["rationale_cited_columns"] = str(getattr(row, "rationale_cited_columns", ""))
        r["sim_label"] = str(getattr(row, "sim_label", ""))
        t.write_row(i, r)
    t.freeze("lane")
    sh.after(t)

    sh.section("Hedge stack — MASTER_SPEC Table 4 row 2.7 (a) MCX tranches and rolls, (b) USD/INR forwards")
    sh.note("Executed decisions only (lots, notionals, dates, the rate actually dealt). Prices are recomputed on "
            "Cashflows and MTM_Daily, never typed here.")
    ht = _hedges(sh, data)
    sh.after(ht)
    return {"tickets": t, "hedges": ht}


HEDGE_COLS = [("trade_id", 9), ("instrument", 22), ("hedge_id", 14), ("decision_date", 12), ("contract_month", 13),
              ("direct_expiry", 12), ("panel_expiry_slot", 12), ("roll_deadline", 12), ("direction", 10),
              ("lots", 8), ("lot_mt", 8), ("position_mt", 12), ("entry_date", 12), ("exit_date", 12),
              ("exit_reason", 11), ("roll_to", 13), ("entry_price_inr_kg", 13), ("entry_price_src", 12),
              ("exit_price_inr_kg", 13), ("exit_price_src", 12), ("hedge_ratio_target", 12),
              ("hedge_ratio_actual", 12), ("sizing_basis", 60), ("notional_usd", 15), ("booking_date", 12),
              ("value_date", 12), ("cancel_date", 12), ("matched_leg", 18), ("forward_mid_inr", 13),
              ("bank_margin_inr", 12), ("rate_inr", 12), ("index_usd_box_at_fixture", 13),
              ("fixture_vs_index_frac", 12), ("weakest_input_flag", 12)]


def _hedges(sh, data: sources.Data):
    cols = [Column("trade_id", KEY, width=9)]
    cols += [Column(n, INPUT, width=w) for n, w in HEDGE_COLS[1:]]
    cols += [Column("basis_risk_note", KEY, width=120)]
    t = sh.table(cols)
    for i, row in enumerate(data.hedges.itertuples(index=False)):
        r = {n: _cell(getattr(row, n, None)) for n, _w in HEDGE_COLS}
        r["basis_risk_note"] = " ".join(str(getattr(row, "basis_risk_note", "")).split())
        t.write_row(i, r)
    t.freeze("hedge_id")
    return t


def _cell(v):
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date() if pd.notna(v) else None
    if isinstance(v, float) and pd.isna(v):
        return None
    return v
