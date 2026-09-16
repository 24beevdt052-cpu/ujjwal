"""`Counterparties` — `config/counterparties.yaml`, flattened. Every company is FICTIONAL (SIM).

The credit limits here are desk policy decisions, not observations, and are what `desk.book.validate` checks every
sale booking against. The `profile` block exists so the Phase 5 credit model has features that separate; it is
simulated and labelled SIM on every row. Nothing on this sheet is computed — it is an input register, blue
throughout, and the workbook reads it the way the Python book does.
"""

from __future__ import annotations

from desk.excel import sources
from desk.excel.layout import INPUT, KEY, Column, Sheet

SHEET = "Counterparties"

TOP = ["cp_id", "name", "role", "type", "country", "location", "lanes", "grades", "credit_limit_inr",
       "claims_exposure_limit_usd", "default_payment_terms", "default_credit_days", "default_advance_frac",
       "lc_confirmation_required", "safe_origin_for_psic", "msme_registered", "flag"]
PROFILE = ["relationship_start", "years_in_business", "annual_turnover_inr", "prior_invoices_n",
           "prior_dpd_mean_days", "prior_dpd_max_days", "prior_defaults_n", "prior_disputed_claims_n",
           "gst_returns_regular", "internal_rating_sim", "security", "sector", "capacity_mt_pa",
           "order_concentration_note"]


def write(wb, counts, data: sources.Data):
    sh = Sheet(wb, SHEET, "Counterparties — config/counterparties.yaml (every company is SIMULATED)", counts,
               subtitle="Blue = input. Credit limits are desk policy (ASSUMPTION); profile fields are SIM features "
                        "for the Phase 5 credit model. msme_max_payment_days and "
                        "fx_hedge_no_documentation_limit_usd are the DIRECT policy caps these are checked against.")
    cps = data.counterparties["counterparties"]
    prof_keys = [k for k in PROFILE if any(k in (c.get("profile") or {}) for c in cps)]
    cols = [Column("cp_id", KEY, width=14)]
    cols += [Column(c, INPUT, width=_w(c)) for c in TOP[1:]]
    cols += [Column(f"profile.{k}", INPUT, width=_w(k)) for k in prof_keys]
    cols += [Column("note", KEY, width=110)]
    t = sh.table(cols)
    for i, cp in enumerate(cps):
        row = {"cp_id": cp["cp_id"]}
        for k in TOP[1:]:
            v = cp.get(k)
            row[k] = ", ".join(str(x) for x in v) if isinstance(v, list) else v
        prof = cp.get("profile") or {}
        for k in prof_keys:
            v = prof.get(k)
            row[f"profile.{k}"] = ", ".join(str(x) for x in v) if isinstance(v, list) else v
        row["note"] = " ".join(str(cp.get("note", "")).split())
        t.write_row(i, row)
    t.freeze("name")
    sh.after(t)
    return t


def _w(name: str) -> float:
    if name in ("name", "location", "order_concentration_note"):
        return 38
    if name.endswith("_inr") or name.endswith("_usd"):
        return 18
    return 14
