"""Assumptions register loader (Table 8.1: every number traceable to a source or a labelled assumption).

Every parameter lives in exactly one YAML file under config/params/. Each top-level key is one parameter:

    bcd_scrap_hs7602:
      value: 0.025                      # scalar ...
      unit: frac_of_assessable_value
      flag: DIRECT | PROXY | ASSUMPTION
      source: "CBIC Customs Tariff ch.76 ..."
      verify: "PENDING — check notification X"   # or "VERIFIED 2026-09-16 via <url>"
      note: "why this value / range / justification"

    grade_factor_zorba:
      path:                             # ... or a time path instead of `value`
        - [2022-03-01, 0.78]
        - [2022-08-31, 0.82]
      interp: linear                    # linear | step  (step = value holds until next breakpoint)
      unit: frac_of_lme
      flag: ASSUMPTION
      ...

Keys must be globally unique across files (the loader raises on duplicates).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import pandas as pd
import yaml

from desk.paths import PARAMS_DIR

VALID_FLAGS = ("DIRECT", "PROXY", "ASSUMPTION")
REQUIRED_FIELDS = ("unit", "flag", "source", "verify", "note")


@dataclass(frozen=True)
class Param:
    key: str
    unit: str
    flag: str
    source: str
    verify: str
    note: str
    file: str
    value: Any = None
    path: tuple = field(default_factory=tuple)  # ((date, value), ...) sorted by date
    interp: str = "step"

    @property
    def is_path(self) -> bool:
        return bool(self.path)

    def at(self, date) -> Any:
        """Value on `date` (scalars ignore the date; paths clamp at both ends)."""
        if not self.is_path:
            return self.value
        d = pd.Timestamp(date).date()
        dates = [p[0] for p in self.path]
        vals = [p[1] for p in self.path]
        if d <= dates[0]:
            return vals[0]
        if d >= dates[-1]:
            return vals[-1]
        for i in range(1, len(dates)):
            if d < dates[i]:
                if self.interp == "step":
                    return vals[i - 1]
                span = (dates[i] - dates[i - 1]).days
                w = (d - dates[i - 1]).days / span
                return vals[i - 1] + w * (vals[i] - vals[i - 1])
        return vals[-1]

    def series(self, index) -> pd.Series:
        """Vectorised `at` over a DatetimeIndex / iterable of dates."""
        idx = pd.DatetimeIndex(index)
        return pd.Series([self.at(d) for d in idx], index=idx, name=self.key)


def _to_date(x) -> dt.date:
    return x if isinstance(x, dt.date) else pd.Timestamp(x).date()


@lru_cache(maxsize=1)
def load_params() -> dict[str, Param]:
    params: dict[str, Param] = {}
    for f in sorted(PARAMS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(f.read_text()) or {}
        for key, spec in raw.items():
            if key in params:
                raise ValueError(f"Duplicate parameter '{key}' in {f.name} and {params[key].file}")
            missing = [k for k in REQUIRED_FIELDS if k not in spec]
            if missing:
                raise ValueError(f"Parameter '{key}' in {f.name} missing fields {missing}")
            if spec["flag"] not in VALID_FLAGS:
                raise ValueError(f"Parameter '{key}' in {f.name} has invalid flag {spec['flag']!r}")
            has_value, has_path = "value" in spec, "path" in spec
            if has_value == has_path:
                raise ValueError(f"Parameter '{key}' in {f.name} needs exactly one of value/path")
            path = tuple(sorted((_to_date(d), v) for d, v in spec.get("path", [])))
            params[key] = Param(
                key=key,
                unit=str(spec["unit"]),
                flag=spec["flag"],
                source=str(spec["source"]),
                verify=str(spec["verify"]),
                note=str(spec["note"]).strip(),
                file=f.name,
                value=spec.get("value"),
                path=path,
                interp=spec.get("interp", "step"),
            )
    return params


def get(key: str) -> Param:
    params = load_params()
    if key not in params:
        raise KeyError(f"Unknown parameter '{key}'. Add it to a YAML file in {PARAMS_DIR}.")
    return params[key]


def value(key: str, date=None) -> Any:
    p = get(key)
    return p.at(date) if p.is_path else p.value


def params_frame() -> pd.DataFrame:
    """The whole register as a table (feeds docs/assumptions log and the Excel Inputs sheet)."""
    rows = []
    for p in load_params().values():
        rows.append(
            {
                "key": p.key,
                "value": p.value if not p.is_path else "; ".join(f"{d}: {v}" for d, v in p.path),
                "interp": p.interp if p.is_path else "",
                "unit": p.unit,
                "flag": p.flag,
                "source": p.source,
                "verify": p.verify,
                "note": p.note,
                "file": p.file,
            }
        )
    return pd.DataFrame(rows)


def reload() -> None:
    load_params.cache_clear()
