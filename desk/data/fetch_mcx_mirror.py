"""Third-party mirror of MCX Aluminium closes (commoditieschart.net) -> data/interim/ extract. Never DIRECT.

Why this exists: mcxindia.com blocks scripted clients (Akamai HTTP 403), so no bhavcopy could be downloaded in
Phase 0. A public mirror of continuous nearest / second-month MCX Aluminium closes was found and is used ONLY to
calibrate `mcx_domestic_premium_inr_kg` (market_proxy.yaml) and to test the import-parity proxy (Table 1.3). It is not
promoted to DIRECT because its provenance and roll convention cannot be checked against MCX's own files.

Raw pages are cached under data/raw/mcx_thirdparty/ through `fetch_cached` (CONTRACTS §1.7); the parsed extract is a
derived table and goes to data/interim/, outside data/manual/ (which is reserved for drop-in DIRECT files).

What this does and doesn't tell you: the extract shows what a public website republished as MCX closes; it is good
evidence for the proxy's level and weekly direction, not an exchange record.
"""

from __future__ import annotations

from desk.data import mcx
from desk.data._http import fetch_cached
from desk.paths import INTERIM_DIR

PAGES = {
    "m1_close_inr_kg": mcx.THIRDPARTY_NEAREST_HTML,
    "m2_close_inr_kg": mcx.THIRDPARTY_2M_HTML,
    "lme_usd_t": mcx.THIRDPARTY_LME_HTML,
}


def _has_points(body: bytes) -> bool:
    return b'{d:"' in body


def fetch_pages(refresh: bool = False) -> None:
    for key, path in PAGES.items():
        fetch_cached(mcx.THIRDPARTY_URLS[key], path, refresh=refresh, min_bytes=50_000, validator=_has_points)


def main() -> None:
    fetch_pages()
    df = mcx.build_thirdparty_csv()
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(mcx.THIRDPARTY_CSV, index=False, lineterminator="\n")
    print(f"[fetch_mcx_mirror] third-party mirror extract (PROXY evidence, not DIRECT): {len(df)} rows -> "
          f"{mcx.THIRDPARTY_CSV}")


if __name__ == "__main__":
    main()
