import datetime as dt

import pytest

from desk import config, units


def test_register_loads_and_is_well_formed():
    frame = config.params_frame()
    assert len(frame) > 0
    assert set(frame["flag"]) <= set(config.VALID_FLAGS)
    assert frame["key"].is_unique


def test_step_path_holds_until_next_breakpoint():
    repo = config.get("rbi_repo_rate_pa")
    assert repo.at(dt.date(2022, 5, 3)) == pytest.approx(0.04)
    assert repo.at(dt.date(2022, 5, 4)) == pytest.approx(0.044)
    assert repo.at(dt.date(2022, 8, 31)) == pytest.approx(0.054)


def test_unit_round_trips():
    assert units.inr_kg_to_inr_t(units.inr_t_to_inr_kg(250_000.0)) == pytest.approx(250_000.0)
    assert units.usd_t_to_inr_kg(3000.0, 80.0) == pytest.approx(240.0)
    assert units.mt_to_lots(1002.0, 5.0) == 200


def test_fx_forward_is_above_spot_when_inr_rates_exceed_usd():
    assert units.fx_forward(76.0, 0.05, 0.01, 90) > 76.0
