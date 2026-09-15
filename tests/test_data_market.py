"""Phase 0 market data: LME (Westmetall), USD/INR + rates + CIP forwards, MCX proxy / manual loader."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
import requests

from desk import config, units
from desk.data import _http, fetch_fx, fetch_lme, mcx
from desk.paths import PROCESSED_DIR

LME_CSV = PROCESSED_DIR / "lme_daily.csv"
FX_CSV = PROCESSED_DIR / "fx_rates_daily.csv"


def _need(*paths):
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"run the fetchers first; missing {missing}")


@pytest.fixture(scope="module")
def lme() -> pd.DataFrame:
    _need(LME_CSV)
    return pd.read_csv(LME_CSV, parse_dates=["date"])


@pytest.fixture(scope="module")
def fx() -> pd.DataFrame:
    _need(FX_CSV)
    return pd.read_csv(FX_CSV, parse_dates=["date"])


@pytest.fixture(scope="module")
def mini_panel(lme, fx) -> pd.DataFrame:
    """LME calendar with FX forward-filled — the shape build_panel hands to load_or_proxy_mcx."""
    f = fx.set_index("date")[["usdinr", "inr_rate_3m_pa"]]
    f = f.reindex(f.index.union(lme["date"])).ffill().reindex(lme["date"])
    return pd.DataFrame({"date": lme["date"].to_numpy(), "lme_cash_usd_t": lme["lme_cash_usd_t"].to_numpy(),
                         "usdinr": f["usdinr"].to_numpy(), "inr_rate_3m_pa": f["inr_rate_3m_pa"].to_numpy()})


# ------------------------------------------------------------------------------------------------ LME
def test_lme_anchor_all_time_high(lme):
    row = lme.set_index("date").loc["2022-03-07"]
    assert row["lme_cash_usd_t"] == 3984.5
    assert row["lme_3m_usd_t"] == 3968.0


def test_lme_contract_columns_and_range(lme):
    assert list(lme.columns) == fetch_lme.COLUMNS
    assert lme["date"].iloc[0] == pd.Timestamp("2018-01-02")
    assert lme["date"].iloc[-1] == pd.Timestamp("2022-12-30")
    counts = lme.groupby(lme["date"].dt.year).size()
    assert counts.between(fetch_lme.MIN_ROWS_PER_YEAR, fetch_lme.MAX_ROWS_PER_YEAR).all()


def test_no_duplicate_dates(lme, fx):
    for df in (lme, fx):
        assert df["date"].is_unique
        assert df["date"].is_monotonic_increasing


def test_spread_sign_convention(lme):
    spread = lme["lme_cash_usd_t"] - lme["lme_3m_usd_t"]
    assert np.allclose(lme["lme_cash_3m_spread_usd_t"], spread)
    by_date = lme.set_index("date")
    # 7 Mar 2022: cash above 3M -> backwardation -> positive spread.
    assert by_date.loc["2022-03-07", "lme_cash_3m_spread_usd_t"] == pytest.approx(16.5)
    # Both regimes occur in the history, so the sign is informative rather than constant.
    assert (spread > 0).any() and (spread < 0).any()


def test_westmetall_parser_handles_headers_separators_and_blanks():
    page = """
    <table><thead><tr class="shaded"><th>date</th><th>Cash</th><th>3-month</th><th>stock</th></tr></thead><tbody>
    <tr><td >31. March 2022</td><td >3,503.00</td><td >3,518.00</td><td class="last">646,850</td></tr>
    <tr class="shaded"><th class="text">date</th><th>Cash</th><th>3-month</th><th class="text last">stock</th></tr>
    <tr><td >07. March 2022</td><td >3,984.50</td><td >3,968.00</td><td class="last"></td></tr>
    </tbody></table>"""
    df = fetch_lme.parse_westmetall_html(page)
    assert len(df) == 2
    assert df.iloc[1]["date"] == dt.date(2022, 3, 7)
    assert df.iloc[1]["lme_cash_usd_t"] == 3984.5
    assert np.isnan(df.iloc[1]["lme_stock_mt"])
    assert df.iloc[0]["lme_stock_mt"] == 646850


# ------------------------------------------------------------------------------------------------ FX / rates
def test_fx_contract_columns(fx):
    assert fetch_fx.COLUMNS == [
        "date", "usdinr", "usdinr_src", "rbi_repo_pa", "fed_funds_upper_pa", "inr_rate_3m_pa", "usd_rate_3m_pa",
        "usd_rate_3m_filled", "rates_src", "fwd_premium_3m_pa", "usdinr_fwd_1m", "usdinr_fwd_3m"]  # CONTRACTS §4.2
    assert list(fx.columns) == fetch_fx.COLUMNS
    assert not fx.isna().any().any()
    assert set(fx["usdinr_src"]) <= {"ECB_CROSS", "MANUAL_RBI"}
    assert fx["rates_src"].str.fullmatch(r"USD:(UST13W|FALLBACK_FEDFUNDS_SPREAD)\|INR:(OECD_IR3TIB|FALLBACK_REPO_SPREAD)").all()


def test_offline_treasury_cache_miss_raises_instead_of_silent_fallback(tmp_path, monkeypatch):
    """Review finding: a missing cache used to rewrite usd_rate_3m_pa on every row and exit 0 offline."""
    monkeypatch.setenv("DESK_OFFLINE", "1")
    monkeypatch.setattr(fetch_fx, "RATES_RAW_DIR", tmp_path)  # every Treasury cache is now 'missing'
    with pytest.raises(_http.FetchError):
        fetch_fx.build_rates(pd.DatetimeIndex(pd.to_datetime(["2022-03-01", "2022-03-02"])))


def test_online_treasury_failure_falls_back_per_year_and_is_labelled(monkeypatch):
    real = fetch_fx.fetch_ust_13w

    def one_year_missing(refresh=False):
        s, missing = real(refresh)
        return s[s.index.year != 2022], [*missing, 2022]

    monkeypatch.setenv("DESK_OFFLINE", "1")
    monkeypatch.setattr(fetch_fx, "fetch_ust_13w", one_year_missing)
    idx = pd.DatetimeIndex(pd.to_datetime(["2021-12-30", "2022-03-01", "2022-06-15"]))
    out = fetch_fx.build_rates(idx)
    assert out.loc["2021-12-30", "rates_src"].startswith("USD:UST13W")
    assert out.loc["2022-06-15", "rates_src"].startswith("USD:FALLBACK_FEDFUNDS_SPREAD")
    fb = config.value("fed_funds_upper_pa", "2022-06-15") + config.value("usd_term_spread_3m_pa")
    assert out.loc["2022-06-15", "usd_rate_3m_pa"] == pytest.approx(fb)


def test_usdinr_2022_band(fx):
    y2022 = fx[fx["date"].dt.year == 2022]["usdinr"]
    assert len(y2022) > 250
    assert y2022.between(70, 84).all()


def test_usdinr_is_ecb_cross(fx):
    inr, usd = fetch_fx.fetch_ecb("INR"), fetch_fx.fetch_ecb("USD")
    d = pd.Timestamp("2022-03-07")
    got = fx.set_index("date").loc[d, "usdinr"]
    assert got == pytest.approx(inr[d] / usd[d], abs=5e-5)


def test_forward_above_spot_when_inr_rate_exceeds_usd(fx):
    assert units.fx_forward(76.0, 0.05, 0.01, 90) > 76.0
    assert units.fx_forward(76.0, 0.01, 0.05, 90) < 76.0
    higher = fx["inr_rate_3m_pa"] / 365 > fx["usd_rate_3m_pa"] / 360
    assert higher.any()
    assert (fx.loc[higher, "usdinr_fwd_3m"] > fx.loc[higher, "usdinr"]).all()
    assert (fx.loc[higher, "usdinr_fwd_3m"] > fx.loc[higher, "usdinr_fwd_1m"]).all()


def test_forward_reproduces_cip_by_hand(fx):
    row = fx.set_index("date").loc["2022-06-15"]
    days = (pd.Timestamp("2022-09-15") - pd.Timestamp("2022-06-15")).days
    fwd = row["usdinr"] * (1 + row["inr_rate_3m_pa"] * days / 365) / (1 + row["usd_rate_3m_pa"] * days / 360)
    assert row["usdinr_fwd_3m"] == pytest.approx(fwd, abs=2e-3)
    assert row["fwd_premium_3m_pa"] == pytest.approx((fwd / row["usdinr"] - 1) * 365 / days, abs=2e-4)


def test_policy_rate_paths_cover_history_with_verified_steps(fx):
    repo, fed = config.get("rbi_repo_rate_pa"), config.get("fed_funds_upper_pa")
    assert repo.at(dt.date(2017, 12, 1)) == pytest.approx(0.06)
    assert repo.at(dt.date(2019, 10, 4)) == pytest.approx(0.0515)
    assert repo.at(dt.date(2022, 5, 3)) == pytest.approx(0.04)
    assert repo.at(dt.date(2022, 12, 30)) == pytest.approx(0.0625)
    assert fed.at(dt.date(2017, 12, 13)) == pytest.approx(0.0125)
    assert fed.at(dt.date(2017, 12, 14)) == pytest.approx(0.015)
    assert fed.at(dt.date(2022, 3, 16)) == pytest.approx(0.0025)
    assert fed.at(dt.date(2022, 12, 30)) == pytest.approx(0.045)
    assert repo.verify.startswith("VERIFIED") and fed.verify.startswith("VERIFIED")
    by_date = fx.set_index("date")
    assert by_date.loc["2022-08-05", "rbi_repo_pa"] == pytest.approx(0.054)


def test_manual_rbi_override(tmp_path, monkeypatch):
    _need(fetch_fx.ecb_cache_path("INR"), fetch_fx.ecb_cache_path("USD"))
    manual = tmp_path / "rbi_reference_rate.csv"
    manual.write_text("date,usdinr,source\n2022-03-07,77.0,RBI reference rate - unit-test placeholder not data\n")
    monkeypatch.setenv("DESK_OFFLINE", "1")
    monkeypatch.setattr(fetch_fx, "MANUAL_RBI_PATH", manual)
    spot = fetch_fx.build_spot()
    assert spot.loc["2022-03-07", "usdinr_src"] == "MANUAL_RBI"
    assert spot.loc["2022-03-07", "usdinr"] == 77.0
    assert spot.loc["2022-03-08", "usdinr_src"] == "ECB_CROSS"


def test_manual_rbi_without_named_source_is_rejected(tmp_path, monkeypatch):
    for body in ("date,usdinr\n2022-03-07,77.0\n", "date,usdinr,source\n2022-03-07,77.0,my notes\n"):
        f = tmp_path / "rbi_reference_rate.csv"
        f.write_text(body)
        with pytest.raises(ValueError, match="source"):
            fetch_fx.load_manual_rbi(f)


# ------------------------------------------------------------------------------------------------ MCX
def test_mcx_proxy_formula_by_hand(mini_panel, tmp_path):
    out = mcx.load_or_proxy_mcx(mini_panel, manual_dir=tmp_path)  # empty dir -> proxy on every day
    row = out.set_index("date").loc["2022-03-07"]
    p = mini_panel.set_index("date").loc["2022-03-07"]
    d = "2022-03-07"
    bcd, sws = config.value("bcd_primary_al_hs7601", d), config.value("sws_rate_on_bcd", d)
    prem = config.value("mcx_domestic_premium_inr_kg", d)
    spot = p["lme_cash_usd_t"] * p["usdinr"] / 1000 * (1 + bcd * (1 + sws)) + prem
    assert row["mcx_al_spot_inr_kg"] == pytest.approx(spot, abs=1e-3)
    # March 2022 contract expires Thu 31-Mar (a panel day); April's last calendar day is a Saturday -> Fri 29-Apr.
    assert row["mcx_m1_expiry"] == "2022-03-31" and row["mcx_m2_expiry"] == "2022-04-29"
    m1 = spot * (1 + p["inr_rate_3m_pa"] * 24 / 365)
    m2 = spot * (1 + p["inr_rate_3m_pa"] * 53 / 365)
    assert row["mcx_al_m1_inr_kg"] == pytest.approx(m1, abs=1e-3)
    assert row["mcx_al_m2_inr_kg"] == pytest.approx(m2, abs=1e-3)
    assert row["mcx_src"] == mcx.SRC_PROXY


def test_mcx_contract_rolls_after_expiry():
    days = pd.bdate_range("2022-03-28", "2022-04-05")
    cal = mcx.contract_calendar(days)
    assert cal.loc["2022-03-31", "mcx_m1_expiry"] == pd.Timestamp("2022-03-31")
    assert cal.loc["2022-04-01", "mcx_m1_expiry"] == pd.Timestamp("2022-04-29")
    assert cal.loc["2022-04-01", "mcx_m2_expiry"] == pd.Timestamp("2022-05-31")


def test_mcx_manual_bhavcopy_loader(tmp_path):
    panel = pd.DataFrame({"date": pd.to_datetime(["2022-03-30", "2022-03-31", "2022-04-01", "2022-04-04"]),
                          "lme_cash_usd_t": 3500.0, "usdinr": 76.0, "inr_rate_3m_pa": 0.04})
    src = "MCX bhavcopy unit-test placeholder (not data)"
    (tmp_path / "mcx_aluminium_test.csv").write_text(
        "date,contract_expiry,close_inr_kg,source\n"
        f"2022-03-30,2022-03-31,280.0,{src}\n2022-03-30,2022-04-29,282.0,{src}\n2022-03-30,2022-05-31,284.0,{src}\n"
        f"2022-03-31,2022-03-31,281.0,{src}\n2022-03-31,2022-04-29,283.0,{src}\n2022-03-31,2022-05-31,285.0,{src}\n"
        f"2022-04-01,2022-04-29,279.0,{src}\n2022-04-01,2022-05-31,281.0,{src}\n"
        f"2022-04-05,2022-04-29,278.0,{src}\n2022-04-05,2022-05-31,280.0,{src}\n"
    )
    panel = pd.concat([panel, pd.DataFrame({"date": pd.to_datetime(["2022-04-05", "2022-04-06", "2022-04-07"]),
                                            "lme_cash_usd_t": 3500.0, "usdinr": 76.0, "inr_rate_3m_pa": 0.04})],
                      ignore_index=True)
    out = mcx.load_or_proxy_mcx(panel, manual_dir=tmp_path).set_index("date")
    assert out.loc["2022-03-31", "mcx_al_m1_inr_kg"] == 281.0
    assert out.loc["2022-03-31", "mcx_src"] == mcx.SRC_MANUAL
    assert out.loc["2022-04-01", "mcx_m1_expiry"] == "2022-04-29"
    assert out.loc["2022-04-01", "mcx_al_m2_inr_kg"] == 281.0
    # 4 Apr has no MCX row but 5 Apr does: an MCX non-trading day inside coverage, carried from 1 Apr and flagged.
    assert out.loc["2022-04-04", "mcx_src"] == mcx.SRC_MANUAL_FFILL
    assert out.loc["2022-04-04", "mcx_al_m1_inr_kg"] == 279.0
    spot = 279.0 / (1 + 0.04 * (pd.Timestamp("2022-04-29") - pd.Timestamp("2022-04-04")).days / 365)
    assert out.loc["2022-04-04", "mcx_al_spot_inr_kg"] == pytest.approx(spot, abs=1e-3)
    # After the last manual date the stale close is NOT extended: those days fall back to the proxy.
    assert out.loc["2022-04-05", "mcx_src"] == mcx.SRC_MANUAL
    assert (out.loc["2022-04-06":"2022-04-07", "mcx_src"] == mcx.SRC_PROXY).all()


def test_mcx_manual_file_without_named_source_is_rejected(tmp_path):
    panel = pd.DataFrame({"date": pd.to_datetime(["2022-03-31"]), "lme_cash_usd_t": 3500.0, "usdinr": 76.0,
                          "inr_rate_3m_pa": 0.04})
    (tmp_path / "mcx_aluminium_x.csv").write_text("date,contract_expiry,close_inr_kg\n2022-03-31,2022-03-31,281.0\n")
    with pytest.raises(ValueError, match="source"):
        mcx.load_or_proxy_mcx(panel, manual_dir=tmp_path)
    (tmp_path / "mcx_aluminium_x.csv").write_text(
        "date,contract_expiry,close_inr_kg,source\n2022-03-31,2022-03-31,281.0,copied from a website\n")
    with pytest.raises(ValueError, match="bhavcopy"):
        mcx.load_or_proxy_mcx(panel, manual_dir=tmp_path)


def test_thirdparty_mirror_not_auto_promoted_to_direct():
    from desk.paths import INTERIM_DIR, MANUAL_DIR, RAW_DIR

    assert not mcx.THIRDPARTY_CSV.match(mcx.MANUAL_GLOB)
    assert mcx.THIRDPARTY_CSV.parent == INTERIM_DIR
    assert mcx.THIRDPARTY_NEAREST_HTML.parent == RAW_DIR / "mcx_thirdparty"
    assert not list(MANUAL_DIR.glob("*thirdparty*"))  # data/manual is reserved for drop-in DIRECT files


# ------------------------------------------------------------------------------------------------ offline cache
def test_offline_mode_rebuilds_identical_outputs_from_cache(monkeypatch, lme, fx):
    _need(*[fetch_lme.raw_path(y) for y in fetch_lme.YEARS])
    monkeypatch.setenv("DESK_OFFLINE", "1")

    def _no_network(*args, **kwargs):
        raise AssertionError("network used while DESK_OFFLINE=1")

    monkeypatch.setattr(requests.Session, "get", _no_network)
    rebuilt_lme = fetch_lme.build()
    fetch_lme.validate(rebuilt_lme)
    rebuilt_lme["date"] = pd.to_datetime(rebuilt_lme["date"])
    pd.testing.assert_frame_equal(rebuilt_lme.reset_index(drop=True), lme, check_dtype=False)

    rebuilt_fx = fetch_fx.build()
    rebuilt_fx["date"] = pd.to_datetime(rebuilt_fx["date"])
    pd.testing.assert_frame_equal(rebuilt_fx.reset_index(drop=True), fx, check_dtype=False, atol=1e-9)


def test_offline_mode_refuses_network_on_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_OFFLINE", "1")
    with pytest.raises(_http.FetchError):
        _http.fetch_cached("https://example.invalid/x", tmp_path / "missing.bin")
