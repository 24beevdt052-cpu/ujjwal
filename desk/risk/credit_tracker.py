"""Credit tracker (MASTER_SPEC Table 6 row 4.4): counterparty exposure vs limits, breach flags, 4.3 score bands.

Everything here is point-in-time. For each panel day `d` the tracker reads only rows dated on or before `d`:

* **Exposure measures come from Phase 3, not from a re-implementation.** `receivable_inr`, `presettlement_inr` and
  `contracted_inr` are `buyer_credit_exposure_by_trade_daily.csv` summed over trades (the per-buyer grain; the
  `buyer_id` in `book_exposures_daily.csv` is compound on T01). `days_past_due` is P3's trade-level column mapped to
  the buyer. P3 splits an unsettled sale flow into receivable or pre-settlement by the flow's *fixing* date, so on a
  fixed-price sale the credit balance counts as receivable from the contract date even before the invoice
  (T07 S1: from 26-Jul, invoiced 16-Aug) — the tracker keeps that definition so its numbers tie to docs/31 §3.4.
* **Two limit measures, both published.** The hard breach the brief asks for is P3's receivable over the limit.
  The *credit utilisation* the model and the band policy use is the desk's own limit definition
  (config/counterparties.yaml header, docs/20 rule C1 — the measure rule P04 checks at bookings) evaluated daily:
  receivable plus the contracted-not-invoiced value an advance does not cover. Advances still owed are neither;
  they are performance exposure and get their own column, flag and overlay.
* **Advance reliance** is the one measure P3 does not publish: advances contracted and not yet received. The amount
  is the booking-time figure P2's rule P04 already computed (`trade_credit_exposure.csv`: invoice value − credit
  value), and the receipt date is the `SALE_ADVANCE` settle date in `trade_cashflows.csv` (REALISED). On day `d` a
  desk knows an advance has not arrived; it does not know when it will, so `CreditInputs.truncated` blanks every
  settle date after the cut-off and the tracker must give the same answer.
* **Scores** use the four features of `credit_scoring.FEATURES` computed from those rows with trailing windows
  (`rolling("91D")`, `rolling("365D")` on the date index — windows that cannot see forward), the static SIM profile
  (relationship start, prior worst DPD, turnover) and the synthetic-trained model, which never saw the book.

Suppliers are tracked against their claims limit (what the desk may be owed BY a seller) but not scored: the
logistic model is a model of a buyer failing to pay for goods on credit, and none of its four features describes a
supplier's claims or refund risk.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from desk import SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.book import schema as bs
from desk.paths import CONFIG_DIR, PROCESSED_DIR, TABLES_DIR
from desk.risk import credit_scoring as cs

EVENT_SEP = "; "
BUYER_ROLE, SUPPLIER_ROLE = "BUYER", "SUPPLIER"
NOT_SCORED = "NOT_SCORED"


# ------------------------------------------------------------------------------------------------ inputs
@dataclass(frozen=True)
class CreditInputs:
    calendar: pd.DatetimeIndex            # engine panel days (book rows of book_exposures_daily.csv)
    expo_by_trade: pd.DataFrame           # date, trade_id, buyer_id, receivable/presettlement/contracted
    trade_rows: pd.DataFrame              # date, trade_id, buyer_id (maybe compound), supplier_id, dpd, supplier exp
    bookings: pd.DataFrame                # P2 booking-time credit table, one row per sale
    advance_receipts: pd.DataFrame        # trade_id, sale_id, received_date (NaT = not yet received)
    balance_flows: pd.DataFrame           # trade_id, sale_id, due_date, paid_date (NaT = not yet paid)
    invoice_dates: pd.DataFrame           # trade_id, sale_id, invoice_date
    usdinr: pd.Series                     # panel usdinr by date
    counterparties: tuple[bs.Counterparty, ...]
    cutoff: pd.Timestamp | None = None

    def truncated(self, cutoff) -> "CreditInputs":
        """The inputs as a desk would hold them at the close of `cutoff`: nothing dated later exists."""
        c = pd.Timestamp(cutoff)

        def blank_after(frame: pd.DataFrame, col: str) -> pd.DataFrame:
            f = frame.copy()
            f.loc[f[col] > c, col] = pd.NaT
            return f

        bookings = self.bookings[self.bookings["contract_date"] <= c]
        keep = set(zip(bookings["trade_id"], bookings["sale_id"]))

        def only_booked(frame: pd.DataFrame) -> pd.DataFrame:
            return frame[[k in keep for k in zip(frame["trade_id"], frame["sale_id"])]]

        return replace(
            self,
            calendar=self.calendar[self.calendar <= c],
            expo_by_trade=self.expo_by_trade[self.expo_by_trade["date"] <= c],
            trade_rows=self.trade_rows[self.trade_rows["date"] <= c],
            bookings=bookings,
            advance_receipts=blank_after(only_booked(self.advance_receipts), "received_date"),
            balance_flows=blank_after(only_booked(self.balance_flows), "paid_date"),
            invoice_dates=blank_after(only_booked(self.invoice_dates), "invoice_date"),
            usdinr=self.usdinr[self.usdinr.index <= c],
            cutoff=c,
        )


def _dates(frame: pd.DataFrame, cols) -> pd.DataFrame:
    for c in cols:
        frame[c] = pd.to_datetime(frame[c])
    return frame


def load_inputs() -> CreditInputs:
    expo = _dates(pd.read_csv(TABLES_DIR / "buyer_credit_exposure_by_trade_daily.csv"), ["date"])
    rows = _dates(pd.read_csv(TABLES_DIR / "book_exposures_daily.csv",
                              usecols=["date", "scope", "trade_id", "buyer_id", "supplier_id",
                                       "supplier_exposure_inr", "days_past_due"]), ["date"])
    calendar = pd.DatetimeIndex(sorted(rows.loc[rows["scope"] == "book", "date"].unique()))
    rows = rows[rows["scope"] == "trade"].drop(columns="scope").reset_index(drop=True)
    bookings = _dates(pd.read_csv(TABLES_DIR / "trade_credit_exposure.csv"), ["contract_date", "due_date"])
    bookings["advance_value_inr"] = (bookings["invoice_value_inr"] - bookings["credit_value_inr"]).clip(lower=0.0)
    bookings = bookings.sort_values(["contract_date", "trade_id", "sale_id"]).reset_index(drop=True)

    cf = pd.read_csv(TABLES_DIR / "trade_cashflows.csv",
                     usecols=["scenario", "trade_id", "leg_id", "leg_type", "due_date_contractual", "settle_date",
                              "amount_inr"])
    cf = cf[(cf["scenario"] == "REALISED") & cf["leg_type"].isin(["SALE_ADVANCE", "SALE_BALANCE"])].copy()
    cf["sale_id"] = cf["leg_id"].str.split(":").str[1]
    cf = _dates(cf, ["due_date_contractual", "settle_date"])
    adv = (cf[cf["leg_type"] == "SALE_ADVANCE"][["trade_id", "sale_id", "settle_date", "amount_inr"]]
           .rename(columns={"settle_date": "received_date", "amount_inr": "realised_advance_inr"}))
    bal = (cf[cf["leg_type"] == "SALE_BALANCE"][["trade_id", "sale_id", "due_date_contractual", "settle_date",
                                                "amount_inr"]]
           .rename(columns={"due_date_contractual": "due_date", "settle_date": "paid_date",
                            "amount_inr": "realised_balance_inr"}))

    tb = pd.read_csv(TABLES_DIR / "trade_book.csv", usecols=["trade_id", "sale_ids", "sale_invoice_dates"])
    inv = []
    for r in tb.itertuples():
        for sid, d in zip(str(r.sale_ids).split(" | "), str(r.sale_invoice_dates).split(" | ")):
            inv.append({"trade_id": r.trade_id, "sale_id": sid.strip(), "invoice_date": pd.Timestamp(d.strip())})
    fx = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "usdinr"], parse_dates=["date"])
    usdinr = fx.set_index("date")["usdinr"]
    usdinr = usdinr[(usdinr.index >= calendar.min()) & (usdinr.index <= calendar.max())]
    cps = tuple(bs.load_counterparties(CONFIG_DIR / "counterparties.yaml"))
    return CreditInputs(calendar=calendar, expo_by_trade=expo, trade_rows=rows, bookings=bookings,
                        advance_receipts=adv.reset_index(drop=True), balance_flows=bal.reset_index(drop=True),
                        invoice_dates=pd.DataFrame(inv), usdinr=usdinr, counterparties=cps)


# ------------------------------------------------------------------------------------------------ exposures
def _buyers(inputs: CreditInputs) -> list[bs.Counterparty]:
    return sorted((c for c in inputs.counterparties if c.role is bs.Role.BUYER), key=lambda c: c.cp_id)


def _suppliers(inputs: CreditInputs) -> list[bs.Counterparty]:
    return sorted((c for c in inputs.counterparties if c.role is bs.Role.SUPPLIER), key=lambda c: c.cp_id)


def buyer_dpd(inputs: CreditInputs) -> pd.DataFrame:
    """Date x buyer days past due from P3's trade rows. A compound buyer_id (T01) is resolved to the buyer(s) with a
    receivable on that trade that day; if none can be identified the delinquency is charged to every buyer on the
    ticket (conservative). On this book only T07 ever runs past due, and it has one buyer."""
    r = inputs.trade_rows[inputs.trade_rows["days_past_due"] > 0]
    expo = inputs.expo_by_trade
    out = []
    for row in r.itertuples():
        names = [b for b in str(row.buyer_id).split(",") if b and b != "nan"]
        if len(names) > 1:
            m = expo[(expo["date"] == row.date) & (expo["trade_id"] == row.trade_id) & (expo["receivable_inr"] > 0)]
            names = sorted(set(m["buyer_id"])) or names
        for b in names:
            out.append({"date": row.date, "cp_id": b, "days_past_due": int(row.days_past_due)})
    if not out:
        return pd.DataFrame(columns=["date", "cp_id", "days_past_due"])
    return pd.DataFrame(out).groupby(["date", "cp_id"], as_index=False)["days_past_due"].max()


def buyer_daily(inputs: CreditInputs) -> pd.DataFrame:
    """Date x buyer exposure measures on the engine calendar (zeros on days with nothing open)."""
    cal = inputs.calendar
    agg = (inputs.expo_by_trade.groupby(["date", "buyer_id"])[["receivable_inr", "presettlement_inr", "contracted_inr"]]
           .sum())
    dpd = buyer_dpd(inputs).set_index(["date", "cp_id"])["days_past_due"]
    frames = []
    for cp in _buyers(inputs):
        f = pd.DataFrame(index=cal)
        f.index.name = "date"
        sub = agg.xs(cp.cp_id, level="buyer_id") if cp.cp_id in agg.index.get_level_values("buyer_id") else None
        for col in ("receivable_inr", "presettlement_inr", "contracted_inr"):
            f[col] = sub[col].reindex(cal).fillna(0.0).to_numpy() if sub is not None else 0.0
        adv = np.zeros(len(cal))
        bk = inputs.bookings[(inputs.bookings["buyer_id"] == cp.cp_id) & (inputs.bookings["advance_value_inr"] > 0)]
        for b in bk.itertuples():
            rec = inputs.advance_receipts[(inputs.advance_receipts["trade_id"] == b.trade_id)
                                          & (inputs.advance_receipts["sale_id"] == b.sale_id)]["received_date"]
            received = rec.iloc[0] if len(rec) else pd.NaT
            pending = (cal >= b.contract_date) & ((cal < received) if pd.notna(received) else True)
            adv += np.where(pending, b.advance_value_inr, 0.0)
        f["advance_pending_inr"] = adv
        if cp.cp_id in dpd.index.get_level_values("cp_id"):
            f["days_past_due"] = dpd.xs(cp.cp_id, level="cp_id").reindex(cal).fillna(0).astype(int).to_numpy()
        else:
            f["days_past_due"] = 0
        f["cp_id"] = cp.cp_id
        frames.append(f.reset_index())
    out = pd.concat(frames, ignore_index=True)
    limits = {c.cp_id: float(c.credit_limit_inr or 0.0) for c in _buyers(inputs)}
    out["credit_limit_inr"] = out["cp_id"].map(limits)
    # P2's P04 measure evaluated daily: receivable plus the part of contracted-not-invoiced value an advance does
    # not cover. Clipped at zero only against float noise; a negative value would mean an advance counted twice.
    out["credit_exposure_p04_basis_inr"] = (out["receivable_inr"] + out["presettlement_inr"]
                                            - out["advance_pending_inr"]).clip(lower=0.0)
    lim = out["credit_limit_inr"].where(out["credit_limit_inr"] > 0)
    out["utilisation_receivable_frac"] = out["receivable_inr"] / lim
    out["utilisation_contracted_frac"] = out["contracted_inr"] / lim
    out["utilisation_p04_basis_frac"] = out["credit_exposure_p04_basis_inr"] / lim
    out["advance_reliance_multiple"] = out["advance_pending_inr"] / lim
    return out


# ------------------------------------------------------------------------------------------------ features
def point_in_time_features(inputs: CreditInputs, daily: pd.DataFrame) -> pd.DataFrame:
    """The four model features plus the overlay trigger, per buyer per panel day, from rows dated <= that day."""
    lb_util = f"{int(config.value('credit_feature_lookback_utilisation_days'))}D"
    lb_dpd = f"{int(config.value('credit_feature_lookback_dpd_days'))}D"
    lb_conc = pd.Timedelta(days=int(config.value("credit_feature_lookback_concentration_days")))
    rm_share = float(config.value("secondary_raw_material_cost_share"))
    frames = []
    for cp in _buyers(inputs):
        f = daily[daily["cp_id"] == cp.cp_id].set_index("date").sort_index()
        p = cp.profile
        out = pd.DataFrame(index=f.index)
        out["cp_id"] = cp.cp_id
        out["utilisation_frac"] = f["utilisation_p04_basis_frac"].rolling(lb_util).max()
        book_dpd = f["days_past_due"].astype(float).rolling(lb_dpd).max()
        out["dpd_max_days"] = np.maximum(float(p.prior_dpd_max_days), book_dpd)
        start = pd.Timestamp(p.relationship_start)
        out["history_months"] = (out.index - start).days / cs.MONTH_DAYS
        bk = inputs.bookings[inputs.bookings["buyer_id"] == cp.cp_id]
        spend = float(p.annual_turnover_inr) * rm_share
        out["order_concentration_frac"] = [
            float(bk.loc[(bk["contract_date"] <= d) & (bk["contract_date"] > d - lb_conc), "invoice_value_inr"].sum())
            / spend for d in out.index]
        out["advance_reliance_peak_multiple"] = f["advance_reliance_multiple"].rolling(lb_util).max()
        out["contracted_utilisation_peak_frac"] = f["utilisation_contracted_frac"].rolling(lb_util).max()
        frames.append(out.reset_index())
    return pd.concat(frames, ignore_index=True)


def score_rows(model: cs.FittedModel, feats: pd.DataFrame) -> pd.DataFrame:
    """PD, model band, performance overlay and final band for any frame carrying the features + overlay trigger."""
    out = feats.copy()
    out["pd_model_annual_frac"] = model.predict(out)
    out["band_model"] = cs.band_from_pd(out["pd_model_annual_frac"].to_numpy())
    cap = float(config.value("buyer_advance_limit_multiple_of_credit_limit"))
    n = int(config.value("credit_performance_overlay_notches"))
    out["overlay_notches"] = np.where(out["advance_reliance_peak_multiple"] > cap, n, 0)
    out["band_final"] = cs.notch(out["band_model"].to_numpy(), out["overlay_notches"].to_numpy())
    return out


# ------------------------------------------------------------------------------------------------ events
def _on_calendar(cal: pd.DatetimeIndex, d: pd.Timestamp) -> pd.Timestamp | None:
    """An event dated on a non-panel day is shown on the next panel day (never an earlier one: no look-ahead)."""
    if pd.isna(d):
        return None
    i = cal.searchsorted(d, side="left")
    return cal[i] if i < len(cal) else None


def _m(x: float) -> str:
    return f"₹{x / 1e6:,.1f}m"


def buyer_events(inputs: CreditInputs) -> dict[tuple[pd.Timestamp, str], list[str]]:
    cal = inputs.calendar
    ev: dict[tuple[pd.Timestamp, str], list[str]] = {}

    def add(d, cp, text):
        day = _on_calendar(cal, d)
        if day is not None:
            ev.setdefault((day, cp), []).append(text)

    for b in inputs.bookings.itertuples():
        tag = f"{b.trade_id}-{b.sale_id}"
        add(b.contract_date, b.buyer_id,
            f"SALE_CONTRACTED {tag} invoice {_m(b.invoice_value_inr)} (advance {_m(b.advance_value_inr)}, "
            f"credit {_m(b.credit_value_inr)}; P04 utilisation after {b.utilisation_frac:.1%})")
        rec = inputs.advance_receipts[(inputs.advance_receipts["trade_id"] == b.trade_id)
                                      & (inputs.advance_receipts["sale_id"] == b.sale_id)]
        for r in rec.itertuples():
            add(r.received_date, b.buyer_id, f"ADVANCE_RECEIVED {tag} {_m(b.advance_value_inr)}")
        inv = inputs.invoice_dates[(inputs.invoice_dates["trade_id"] == b.trade_id)
                                   & (inputs.invoice_dates["sale_id"] == b.sale_id)]
        for r in inv.itertuples():
            add(r.invoice_date, b.buyer_id, f"INVOICED {tag}")
        bal = inputs.balance_flows[(inputs.balance_flows["trade_id"] == b.trade_id)
                                   & (inputs.balance_flows["sale_id"] == b.sale_id)]
        for r in bal.itertuples():
            if b.credit_value_inr <= 0:
                continue
            add(r.due_date, b.buyer_id, f"BALANCE_DUE {tag}")
            if pd.notna(r.paid_date):
                late = (r.paid_date - r.due_date).days
                add(r.paid_date, b.buyer_id,
                    f"BALANCE_PAID {tag}" + (f" {late} days after contractual due" if late > 0 else ""))
    return ev


# ------------------------------------------------------------------------------------------------ the tracker
def _flags(t: pd.DataFrame) -> pd.DataFrame:
    soft = float(config.value("credit_soft_utilisation_frac"))
    p14 = float(config.value("buyer_advance_limit_multiple_of_credit_limit"))
    policy = {b: cs.band_policy(b) for b in cs.BANDS}
    t["band_max_credit_utilisation_frac"] = t["band_final"].map(
        lambda b: policy[b]["band_max_credit_utilisation_frac"])
    t["band_max_advance_reliance_multiple"] = t["band_final"].map(
        lambda b: policy[b]["band_max_advance_reliance_multiple"])
    t["breach_hard_receivable"] = t["receivable_inr"] > t["credit_limit_inr"]
    t["breach_hard_credit_p04_basis"] = t["credit_exposure_p04_basis_inr"] > t["credit_limit_inr"]
    t["flag_soft_utilisation"] = t["utilisation_p04_basis_frac"] >= soft
    t["flag_performance_advance_p14"] = t["advance_reliance_multiple"] > p14
    t["flag_contracted_over_limit"] = t["contracted_inr"] > t["credit_limit_inr"]
    t["flag_past_due"] = t["days_past_due"] > 0
    t["flag_band_utilisation"] = t["utilisation_p04_basis_frac"] > t["band_max_credit_utilisation_frac"]
    t["flag_band_advance"] = t["advance_reliance_multiple"] > t["band_max_advance_reliance_multiple"]
    t["limit_action"] = t["band_final"].map(lambda b: policy[b]["limit_action"])
    t["recommended_limit_inr"] = t["credit_limit_inr"] * t["band_final"].map(lambda b: policy[b]["band_limit_multiplier"])
    return t


BUYER_COLUMNS = [
    "date", "in_window", "cp_id", "cp_name", "role", "credit_limit_inr", "limit_basis",
    "receivable_inr", "presettlement_inr", "contracted_inr", "advance_pending_inr", "credit_exposure_p04_basis_inr",
    "credit_exposure_inr", "utilisation_frac", "utilisation_receivable_frac", "utilisation_contracted_frac",
    "utilisation_p04_basis_frac", "advance_reliance_multiple", "days_past_due",
    "feat_utilisation_peak_91d_frac", "feat_dpd_max_12m_days", "feat_history_months", "feat_order_concentration_frac",
    "advance_reliance_peak_91d_multiple", "contracted_utilisation_peak_91d_frac", "pd_model_annual_frac", "band_model", "overlay_notches", "band_final",
    "band_max_credit_utilisation_frac", "band_max_advance_reliance_multiple",
    "breach_hard", "breach_hard_receivable", "breach_hard_credit_p04_basis", "flag_soft_utilisation", "flag_performance_advance_p14",
    "flag_contracted_over_limit", "flag_past_due", "flag_band_utilisation", "flag_band_advance",
    "limit_action", "recommended_limit_inr", "events", "label",
]
FEATURE_RENAME = {
    "utilisation_frac": "feat_utilisation_peak_91d_frac",
    "dpd_max_days": "feat_dpd_max_12m_days",
    "history_months": "feat_history_months",
    "order_concentration_frac": "feat_order_concentration_frac",
    "advance_reliance_peak_multiple": "advance_reliance_peak_91d_multiple",
    "contracted_utilisation_peak_frac": "contracted_utilisation_peak_91d_frac",
}
TRACKER_LABEL = (f"{SIM_LABEL}. Scores: illustrative logistic model trained on SYNTHETIC data, computed from "
                 f"information dated on or before each row's date")


def buyer_tracker(inputs: CreditInputs, model: cs.FittedModel) -> pd.DataFrame:
    daily = buyer_daily(inputs)
    feats = point_in_time_features(inputs, daily)
    scored = score_rows(model, feats)
    t = daily.merge(scored.rename(columns=FEATURE_RENAME), on=["date", "cp_id"], how="left")
    t = _flags(t)
    names = {c.cp_id: c.name for c in inputs.counterparties}
    ev = buyer_events(inputs)
    t["events"] = [EVENT_SEP.join(ev.get((d, c), [])) for d, c in zip(t["date"], t["cp_id"])]
    t["cp_name"] = t["cp_id"].map(names)
    t["role"] = BUYER_ROLE
    t["limit_basis"] = ("credit exposure = receivable + contracted-not-invoiced not covered by an advance (desk limit "
                        "definition, P04 basis, evaluated daily) vs credit_limit_inr")
    t["credit_exposure_inr"] = t["credit_exposure_p04_basis_inr"]
    t["utilisation_frac"] = t["utilisation_p04_basis_frac"]
    t["breach_hard"] = t["breach_hard_receivable"] | t["breach_hard_credit_p04_basis"]
    t["in_window"] = (t["date"] >= pd.Timestamp(WINDOW_START)) & (t["date"] <= pd.Timestamp(WINDOW_END))
    t["label"] = TRACKER_LABEL
    return t[BUYER_COLUMNS].sort_values(["date", "cp_id"]).reset_index(drop=True)


def supplier_tracker(inputs: CreditInputs) -> pd.DataFrame:
    soft = float(config.value("credit_soft_utilisation_frac"))
    cal = inputs.calendar
    exp = inputs.trade_rows.groupby(["date", "supplier_id"])["supplier_exposure_inr"].sum()
    fx = inputs.usdinr.reindex(cal).ffill()
    frames = []
    for cp in _suppliers(inputs):
        f = pd.DataFrame({"date": cal})
        s = exp.xs(cp.cp_id, level="supplier_id") if cp.cp_id in exp.index.get_level_values("supplier_id") else None
        f["credit_exposure_inr"] = s.reindex(cal).fillna(0.0).to_numpy() if s is not None else 0.0
        f["credit_limit_inr"] = float(cp.claims_exposure_limit_usd or 0.0) * fx.to_numpy()
        f["cp_id"], f["cp_name"], f["role"] = cp.cp_id, cp.name, SUPPLIER_ROLE
        frames.append(f)
    t = pd.concat(frames, ignore_index=True)
    t["limit_basis"] = "claims/refunds owed by supplier (P3 supplier_exposure_inr) vs claims_exposure_limit_usd x usdinr"
    t["utilisation_frac"] = t["credit_exposure_inr"] / t["credit_limit_inr"].where(t["credit_limit_inr"] > 0)
    t["breach_hard"] = t["credit_exposure_inr"] > t["credit_limit_inr"]
    t["flag_soft_utilisation"] = t["utilisation_frac"] >= soft
    t["band_model"] = NOT_SCORED
    t["band_final"] = NOT_SCORED
    t["limit_action"] = "NOT_SCORED — the buyer default model does not describe supplier claims risk; limit monitored only"
    t["events"] = ""
    t["in_window"] = (t["date"] >= pd.Timestamp(WINDOW_START)) & (t["date"] <= pd.Timestamp(WINDOW_END))
    t["label"] = SIM_LABEL
    for c in BUYER_COLUMNS:
        if c not in t.columns:
            # buyer-only flags do not apply to a supplier: False keeps the column boolean across the concat
            t[c] = False if c.startswith(("flag_", "breach_")) else np.nan
    return t[BUYER_COLUMNS].sort_values(["date", "cp_id"]).reset_index(drop=True)


def build_tracker(inputs: CreditInputs, model: cs.FittedModel) -> pd.DataFrame:
    return (pd.concat([buyer_tracker(inputs, model), supplier_tracker(inputs)], ignore_index=True)
            .sort_values(["date", "role", "cp_id"]).reset_index(drop=True))


# ------------------------------------------------------------------------------------------------ bookings
def _credit_days(inputs: CreditInputs) -> dict[tuple[str, str], int]:
    tb = pd.read_csv(TABLES_DIR / "trade_book.csv", usecols=["trade_id", "sale_ids", "sale_credit_days"])
    out = {}
    for r in tb.itertuples():
        days = str(r.sale_credit_days).split("|") if pd.notna(r.sale_credit_days) else []
        for i, sid in enumerate(str(r.sale_ids).split(" | ")):
            v = days[i].strip() if i < len(days) else ""
            out[(r.trade_id, sid.strip())] = int(float(v)) if v not in ("", "nan") else 0
    return out


def booking_checks(inputs: CreditInputs, tracker: pd.DataFrame) -> pd.DataFrame:
    """Every sale booking tested against the band policy in force at the previous close.

    RETROSPECTIVE: the band -> limit policy is a Phase 5 construct; the 2022 SIM desk did not run it. The test asks
    what it would have said using only what was known the day before each booking (the band) plus the booking's own
    terms, which the desk knew when it signed.
    """
    b_tr = tracker[tracker["role"] == BUYER_ROLE].sort_values("date")
    days = _credit_days(inputs)
    rows = []
    for b in inputs.bookings.itertuples():
        hist = b_tr[(b_tr["cp_id"] == b.buyer_id) & (b_tr["date"] < b.contract_date)]
        prev = hist.iloc[-1] if len(hist) else None
        band = prev["band_final"] if prev is not None else None
        pol = cs.band_policy(band) if band else None
        lim = float(b.credit_limit_inr)
        adv_mult = b.advance_value_inr / lim if lim > 0 else np.nan
        cdays = days.get((b.trade_id, b.sale_id), 0)
        reasons = []
        if pol is not None:
            if b.utilisation_frac > pol["band_max_credit_utilisation_frac"] + 1e-9:
                reasons.append(f"P04 utilisation after {b.utilisation_frac:.1%} > band {band} cap "
                               f"{pol['band_max_credit_utilisation_frac']:.0%}")
            if adv_mult > pol["band_max_advance_reliance_multiple"] + 1e-9:
                reasons.append(f"advance reliance {adv_mult:.2f}x limit > band {band} cap "
                               f"{pol['band_max_advance_reliance_multiple']:.2f}x")
            if b.credit_value_inr > 0 and cdays > pol["band_max_credit_days"]:
                reasons.append(f"{cdays} credit days > band {band} cap {pol['band_max_credit_days']}")
        rows.append({
            "contract_date": b.contract_date, "trade_id": b.trade_id, "sale_id": b.sale_id, "cp_id": b.buyer_id,
            "credit_limit_inr": lim, "invoice_value_inr": b.invoice_value_inr, "credit_value_inr": b.credit_value_inr,
            "advance_value_inr": b.advance_value_inr, "advance_reliance_multiple": adv_mult,
            "credit_days": cdays, "p04_utilisation_after_frac": b.utilisation_frac,
            "p14_advance_cap_multiple": float(config.value("buyer_advance_limit_multiple_of_credit_limit")),
            "flag_p14_advance_over_cap": bool(adv_mult > float(config.value("buyer_advance_limit_multiple_of_credit_limit"))),
            "band_as_of_date": prev["date"] if prev is not None else pd.NaT,
            "pd_model_annual_frac_prev_close": prev["pd_model_annual_frac"] if prev is not None else np.nan,
            "band_final_prev_close": band or "",
            "band_max_credit_utilisation_frac": pol["band_max_credit_utilisation_frac"] if pol else np.nan,
            "band_max_advance_reliance_multiple": pol["band_max_advance_reliance_multiple"] if pol else np.nan,
            "band_max_credit_days": pol["band_max_credit_days"] if pol else np.nan,
            "band_policy_verdict": ("NO_PRIOR_SCORE" if pol is None else
                                    "OUTSIDE_BAND_POLICY" if reasons else "WITHIN_BAND_POLICY"),
            "band_policy_reasons": "; ".join(reasons),
            "label": (f"{SIM_LABEL}. RETROSPECTIVE test of the Phase 5 band policy against 2022 SIM bookings, "
                      f"using the band at the previous close; the desk did not run this policy"),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ snapshot
def as_of_rows(tracker: pd.DataFrame, as_of: dt.date) -> pd.DataFrame:
    t = tracker[(tracker["role"] == BUYER_ROLE) & (tracker["date"] <= pd.Timestamp(as_of))]
    last = t["date"].max()
    return t[t["date"] == last].copy()


def features_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """Tracker rows back in model column names (for scoring variants)."""
    inv = {v: k for k, v in FEATURE_RENAME.items()}
    return rows[["cp_id", *inv]].rename(columns=inv)
