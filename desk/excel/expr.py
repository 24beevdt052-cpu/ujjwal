"""Reusable Excel-formula fragments — the workbook's equivalent of `desk.units` and `desk.mtm.curves`.

Each helper returns a formula *string* built from named ranges and `Table` references, so a model change is made in
one place and every sheet that uses it follows. Nothing here evaluates anything in Python.

Two conventions keep the formulas readable and `formulas`-library-safe:

* dates are written as real Excel dates and matched with `MATCH(d, range, 0)` (exact) or `MATCH(d, range, 1)`
  (last breakpoint at or before `d`) — never as text;
* contract months are the integer `YYYYMM`, so an MCX slot can be selected with `=` rather than with `TEXT()`.
"""

from __future__ import annotations

from desk.excel.layout import Table

# ------------------------------------------------------------------------------------------------ register paths
def path_at(key: str, date_ref: str, info: dict) -> str:
    """Value of a dated register parameter on `date_ref`, resolved the way `desk.config.Param.at` resolves it.

    `step`   — the last breakpoint at or before the date, clamped at the first.
    `linear` — linear in calendar days between the bracketing breakpoints, flat outside both ends.
    """
    meta = info[key]
    d, v, n = meta["dates"], meta["values"], meta["n"]
    first = f"INDEX({v},1)"
    last = f"INDEX({v},{n})"
    if meta["interp"] == "step":
        return f"=IF({date_ref}<=INDEX({d},1),{first},INDEX({v},MATCH({date_ref},{d},1)))"
    m = f"MATCH({date_ref},{d},1)"
    lerp = (f"INDEX({v},{m})+({date_ref}-INDEX({d},{m}))/(INDEX({d},{m}+1)-INDEX({d},{m}))"
            f"*(INDEX({v},{m}+1)-INDEX({v},{m}))")
    return (f"=IF({date_ref}<=INDEX({d},1),{first},"
            f"IF({date_ref}>=INDEX({d},{n}),{last},{lerp}))")


def customs_fx_at(date_ref: str, usdinr_ref: str, info: dict) -> str:
    """CBIC notified import rate in force, with the register's documented markup fallback outside the notifications.

    Mirrors `desk.parity.model.customs_fx`: the notified path applies from its first breakpoint until
    `customs_fx_notification_validity_days` after its last; outside that the market rate carries the registered markup.
    """
    step = path_at("customs_usdinr_import", date_ref, info)[1:]
    return (f"=IF(AND({date_ref}>=customs_fx_first,"
            f"{date_ref}<=customs_fx_last+customs_fx_notification_validity_days),"
            f"{step},{usdinr_ref}*(1+customs_fx_markup_frac))")


def customs_fx_src(date_ref: str) -> str:
    return (f'=IF(AND({date_ref}>=customs_fx_first,'
            f'{date_ref}<=customs_fx_last+customs_fx_notification_validity_days),'
            f'"CBIC_NOTIFIED","MARKUP_FALLBACK")')


# ------------------------------------------------------------------------------------------------ panel look-ups
def md(table: Table, column: str, date_ref: str) -> str:
    """Point-in-time panel value: `column` on the exact panel day `date_ref` (Market_Daily)."""
    return f"INDEX({table.abs(column)},MATCH({date_ref},{table.abs('date')},0))"


def md_on_or_before(table: Table, column: str, date_ref: str) -> str:
    """`column` on the latest panel day at or before `date_ref` (the panel is sorted ascending)."""
    return f"INDEX({table.abs(column)},MATCH({date_ref},{table.abs('date')},1))"


def param(key_expr: str) -> str:
    """A register scalar looked up by a key the formula builds, e.g. `param('\"moisture_frac_\"&$C5')`."""
    return f"INDEX(param_values,MATCH({key_expr},param_keys,0))"


# ------------------------------------------------------------------------------------------------ FX and curves
def fx_forward(spot: str, inr_rate: str, usd_rate: str, days: str) -> str:
    """Covered-interest-parity USD/INR forward — `desk.units.fx_forward` (INR ACT/365, USD ACT/360)."""
    return f"({spot}*(1+{inr_rate}*{days}/day_count_inr)/(1+{usd_rate}*{days}/day_count_usd))"


def fx_x(mdt: Table, clock_ref: str, settle_ref: str) -> str:
    """`curves.fx_x`: spot once settled, spot on the settle day itself, the CIP forward to its own settle date before.

    Used for every USD leg, which is what makes a 100 % forward hedge exactly flat in buckets (e) and (g).
    """
    spot = md(mdt, "usdinr", clock_ref)
    inr = md(mdt, "inr_rate_3m_pa", clock_ref)
    usd = md(mdt, "usd_rate_3m_pa", clock_ref)
    past = md_on_or_before(mdt, "usdinr", settle_ref)
    fwd = fx_forward(spot, inr, usd, f"({settle_ref}-{clock_ref})")
    return f"IF({settle_ref}<{clock_ref},{past},IF({settle_ref}={clock_ref},{spot},{fwd}))"


def mcx_theo(mdt: Table, clock_ref: str, month_ref: str) -> str:
    """`curves.mcx_theo`: duty-paid import parity carried to the contract month's panel expiry.

    Every panel day in this workbook is `mcx_src = PROXY_IMPORT_PARITY`, so the cross-exchange basis is zero by
    construction (design D4) and the theoretical price *is* the panel price — the Checks sheet proves it.
    """
    cash = md(mdt, "lme_cash_usd_t", clock_ref)
    fx = md(mdt, "usdinr", clock_ref)
    rate = md(mdt, "inr_rate_3m_pa", clock_ref)
    expiry = f"INDEX(mcx_expiries,MATCH({month_ref},mcx_months,0))"
    dte = f"MAX(0,{expiry}-{clock_ref})"
    spot = f"({cash}*{fx}/kg_per_mt*(1+bcd_primary_al_hs7601*(1+sws_rate_on_bcd))+mcx_domestic_premium_inr_kg)"
    return f"({spot}*(1+{rate}*{dte}/day_count_inr))"


def mcx_settle(mdt: Table, day_ref: str, month_ref: str) -> str:
    """The observed panel settle for a contract month on a past day (M1 or M2 slot, whichever holds that month)."""
    m1m = md(mdt, "mcx_m1_month", day_ref)
    m2m = md(mdt, "mcx_m2_month", day_ref)
    m1 = md(mdt, "mcx_al_m1_inr_kg", day_ref)
    m2 = md(mdt, "mcx_al_m2_inr_kg", day_ref)
    return f"IF({m1m}={month_ref},{m1},IF({m2m}={month_ref},{m2},NA()))"


# ------------------------------------------------------------------------------------------------ helpers
def pass_flag(diff_ref: str, tol_name: str) -> str:
    return f'=IF(ABS({diff_ref})<={tol_name},"PASS","FAIL")'


def box_of(lane_ref: str) -> str:
    return f'IF({lane_ref}="JEA_NSA","20ft","40ft")'


def port_of(lane_ref: str) -> str:
    return f'IF({lane_ref}="JEA_NSA","nsa","mun")'


def psic_key_of(lane_ref: str) -> str:
    return (f'IF({lane_ref}="JEA_NSA","psic_required_uae_origin",'
            f'"psic_required_safe_origin_designated_port")')
