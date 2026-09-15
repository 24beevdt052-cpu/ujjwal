"""Virtual Metals Trading Desk — aluminium scrap imports into India (ACADEMIC SIMULATION)."""

import datetime as _dt

SIM_LABEL = "ACADEMIC SIMULATION — not actual trades"
DESK_NAME = "Meridian Non-Ferrous Trading Pvt Ltd (SIM) — Aluminium Scrap Desk, Mumbai"
BASE_CCY = "INR"

# Headline backtest window (Table 2) and the wider engine horizon (lets trades settle after August).
WINDOW_START = _dt.date(2022, 3, 1)
WINDOW_END = _dt.date(2022, 8, 31)
HORIZON_END = _dt.date(2022, 10, 31)  # every trade cashflow settles by here (CONTRACTS §7)
# Pre-window history used for GARCH lookback and covariance estimation.
HISTORY_START = _dt.date(2018, 1, 2)
# Last day of the Phase 0 market panel (every processed daily/weekly file ends here).
PANEL_END = _dt.date(2022, 12, 30)
# CONTRACTS §3: series on other calendars may be carried forward at most this many business days; longer gaps raise.
MAX_FILL_BDAYS = 5

RNG_SEED = 20220307  # date of the LME all-time high; every stochastic component seeds from this
