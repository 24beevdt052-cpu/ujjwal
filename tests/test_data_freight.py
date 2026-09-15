"""Tests for desk.data.fetch_freight (CONTRACTS §4.3). All tests run offline from the data/raw/freight cache."""

import datetime as dt

import pandas as pd
import pytest

from desk import config
from desk.data import fetch_freight as ff
from desk.data._http import FetchError, fetch_cached

CONTRACT_COLUMNS = [
    "week_end",
    "freight_jea_nsa_usd_t",
    "freight_usec_mun_usd_t",
    "index_name",
    "index_value",
    "freight_src",
    "note",
]
SHAPE_FLAGS = {"WCI_REPORTED", "WCI_DERIVED", "WCI_INTERPOLATED"}
USEC_LEVEL_FLAGS = {"USEC:ANCHORED", "USEC:SIBLING", "USEC:EXTRAP_PRE", "USEC:EXTRAP_POST"}

needs_cache = pytest.mark.skipif(
    not any(ff.WAYBACK_DIR.glob("drewry_wci_*.html")), reason="data/raw/freight cache not present"
)


@pytest.fixture(scope="module")
def built():
    mp = pytest.MonkeyPatch()
    mp.setenv("DESK_OFFLINE", "1")
    try:
        yield ff.build()
    finally:
        mp.undo()


# ---------------------------------------------------------------------------------------------------------------
# output contract
# ---------------------------------------------------------------------------------------------------------------
@needs_cache
def test_schema_matches_contract(built):
    assert list(built.columns) == CONTRACT_COLUMNS


@needs_cache
def test_weekly_friday_index_is_complete(built):
    weeks = pd.DatetimeIndex(built["week_end"])
    expected = pd.date_range("2020-12-25", "2022-12-30", freq="W-FRI")
    assert weeks.equals(expected)
    assert (weeks.dayofweek == 4).all()


@needs_cache
def test_values_positive_and_finite(built):
    for c in ("freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "index_value"):
        assert built[c].notna().all()
        assert (built[c] > 0).all()


@needs_cache
def test_every_row_flags_shape_and_both_levels(built):
    parts = built["freight_src"].str.split("|", expand=True)
    assert set(parts[0]) <= SHAPE_FLAGS
    assert set(parts[1]) <= USEC_LEVEL_FLAGS
    assert set(parts[2]) == {"JEA:ASSUMPTION"}
    assert (built["note"].str.len() > 0).all()
    assert set(built["index_name"]) == {ff.INDEX_NAME}


@needs_cache
def test_mostly_real_index_points(built):
    shape = built["freight_src"].str.split("|").str[0]
    assert (shape == "WCI_REPORTED").mean() >= 0.70
    window = built[(built["week_end"] >= "2022-03-04") & (built["week_end"] <= "2022-09-02")]
    assert (window["freight_src"].str.startswith("WCI_INTERPOLATED")).sum() == 0


@needs_cache
def test_jea_level_equals_register_assumption_at_reference_week(built):
    ref = pd.Timestamp(config.value("freight_jea_nsa_ref_date"))
    row = built.set_index("week_end").loc[ref]
    expected = config.value("freight_jea_nsa_usd_box_ref") / config.value("container_payload_mt_20ft")
    assert row["freight_jea_nsa_usd_t"] == pytest.approx(expected, abs=0.01)


@needs_cache
def test_usec_series_honours_reported_anchor(built):
    # week containing the 30-Aug-2022 Container News USEC->West India average (USD 1,450/FEU)
    row = built.set_index("week_end").loc[pd.Timestamp("2022-09-02")]
    usd_box = row["freight_usec_mun_usd_t"] * config.value("container_payload_mt_40ft")
    assert usd_box == pytest.approx(1450, rel=0.03)


@needs_cache
def test_india_inbound_freight_eased_over_window(built):
    idx = built.set_index("week_end")
    for c in ("freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "index_value"):
        assert idx.loc["2022-08-26", c] < idx.loc["2022-03-04", c]


# ---------------------------------------------------------------------------------------------------------------
# offline behaviour and determinism
# ---------------------------------------------------------------------------------------------------------------
def test_offline_mode_refuses_network_without_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_OFFLINE", "1")
    with pytest.raises(FetchError):
        fetch_cached("https://example.com/never-downloaded", tmp_path / "missing.html")


@needs_cache
def test_offline_build_is_deterministic(built, monkeypatch):
    monkeypatch.setenv("DESK_OFFLINE", "1")
    again = ff.build()
    pd.testing.assert_frame_equal(built, again)


@needs_cache
def test_processed_csv_matches_offline_build(built):
    if not ff.OUT_PATH.exists():
        pytest.skip("freight_weekly.csv not generated yet")
    disk = pd.read_csv(ff.OUT_PATH, parse_dates=["week_end"])
    pd.testing.assert_frame_equal(disk, built, check_dtype=False, atol=1e-9)


# ---------------------------------------------------------------------------------------------------------------
# parsing and gap-filling units (synthetic inputs, no cache needed)
# ---------------------------------------------------------------------------------------------------------------
def _page(sentence: str, date: str) -> bytes:
    return f"<html><body><p>Our detailed assessment for Thursday, {date}</p><p>{sentence}</p></body></html>".encode()


def test_parse_increase_is_not_mistaken_for_decrease():
    # "increased" contains "eased"; the sign must still be positive
    p = ff.parse_wci_snapshot(
        _page("Drewry's composite World Container index increased 19.8% to $5,220.99 per 40ft container.",
              "7 January 2021"), "x")
    assert p.assessed == dt.date(2021, 1, 7)
    assert p.value == pytest.approx(5220.99)
    assert p.wow_pct == pytest.approx(0.198)


def test_parse_decrease_with_dollar_change_and_ajot_wording():
    p = ff.parse_wci_snapshot(
        _page("Drewry's composite World Container index slid 0.1% or $6 to $4,904.75 per 40ft container.",
              "15 April 2021"), "x")
    assert p.wow_pct == pytest.approx(-0.001) and p.wow_usd == pytest.approx(-6)
    q = ff.parse_wci_snapshot(
        _page("Drewry's World Container Index composite index decreased by 0.5% to $7,727.84 per 40ft container",
              "5 May 2022"), "x")
    assert q.value == pytest.approx(7727.84) and q.wow_pct == pytest.approx(-0.005)


def _points(pairs):
    rows = [dict(assessed=pd.Timestamp(d), value=v, wow_pct=pct, wow_usd=usd, snapshot="s", url="u",
                 archive_url="", archived="", retrieved="") for d, v, pct, usd in pairs]
    return pd.DataFrame(rows)


def test_gap_is_derived_from_next_week_change_then_interpolated(monkeypatch):
    monkeypatch.setattr(ff, "FIRST_WEEK", pd.Timestamp("2022-01-07"))
    monkeypatch.setattr(ff, "LAST_WEEK", pd.Timestamp("2022-02-11"))
    pts = _points([
        ("2022-01-06", 1000.0, None, None),
        # 2022-01-13 and 2022-01-20 missing
        ("2022-01-27", 1100.0, None, 50.0),   # => 2022-01-20 derived = 1050
        ("2022-02-03", 1110.0, 0.009, None),
        ("2022-02-10", 1120.0, None, None),
    ])
    wk = ff.weekly_wci(pts)
    assert wk.loc["2022-01-21", "index_value"] == pytest.approx(1050.0)
    assert wk.loc["2022-01-21", "shape_src"] == "WCI_DERIVED"
    assert wk.loc["2022-01-14", "shape_src"] == "WCI_INTERPOLATED"
    assert wk.loc["2022-01-14", "index_value"] == pytest.approx(1025.0)
    assert wk.loc["2022-02-11", "shape_src"] == "WCI_REPORTED"


def test_long_gap_refuses_to_interpolate(monkeypatch):
    monkeypatch.setattr(ff, "FIRST_WEEK", pd.Timestamp("2022-01-07"))
    monkeypatch.setattr(ff, "LAST_WEEK", pd.Timestamp("2022-03-11"))
    pts = _points([("2022-01-06", 1000.0, None, None), ("2022-03-10", 900.0, None, None)])
    with pytest.raises(ValueError, match="gap"):
        ff.weekly_wci(pts)


def test_ratio_path_reproduces_anchors_and_is_flat_outside():
    idx = pd.Series([100.0, 110.0, 120.0, 130.0, 140.0],
                    index=pd.date_range("2022-01-07", periods=5, freq="W-FRI"))
    anchors = pd.DataFrame({"value": [55.0, 70.0]}, index=pd.DatetimeIndex(["2022-01-14", "2022-01-28"]))
    k = ff.ratio_path(idx, anchors)
    lane = idx * k
    assert lane.loc["2022-01-14"] == pytest.approx(55.0)
    assert lane.loc["2022-01-28"] == pytest.approx(70.0)
    assert k.loc["2022-01-07"] == pytest.approx(k.loc["2022-01-14"])
    assert k.loc["2022-02-04"] == pytest.approx(k.loc["2022-01-28"])


# ---------------------------------------------------------------------------------------------------------------
# look-ahead disclosure (review finding: levels are hindsight-calibrated)
# ---------------------------------------------------------------------------------------------------------------
@needs_cache
def test_anchor_available_from_covers_every_input_article(built, monkeypatch):
    monkeypatch.setenv("DESK_OFFLINE", "1")
    anchors = ff.usec_anchor_series(ff.india_inbound_anchors())
    assert (pd.to_datetime(anchors["available_from"]) >= pd.to_datetime(anchors["published"])).all()
    # the June anchor = August level / (1 - July drop) is only knowable once the August article is out
    assert anchors.loc["2022-06-30", "available_from"] == "2022-08-30"
    # sibling anchors depend on the USEC/Europe ratio from articles up to 30-Sep-2022
    assert (anchors.loc[anchors["flag"] == "SIBLING", "available_from"] == "2022-09-30").all()


@needs_cache
def test_weekly_note_discloses_level_publication_date(built):
    notes = built.set_index("week_end")["note"]
    assert notes.str.contains("level inputs public from").all()
    assert "level inputs public from 2022-09-30" in notes.loc[pd.Timestamp("2022-03-04")]


def test_derived_point_tables_live_outside_raw():
    from desk.paths import INTERIM_DIR, RAW_DIR

    for path in (ff.POINTS_WCI, ff.POINTS_ANCHORS):
        assert INTERIM_DIR in path.parents and RAW_DIR not in path.parents
