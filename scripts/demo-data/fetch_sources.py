"""Download and cache the four public sources the demo dataset is built from.

Everything lands under ``.cache/`` (gitignored, see scripts/demo-data/.gitignore) so
re-running ``build_dataset.py`` never re-downloads. See ../../DEMO-DATASET-PLAN.md
§4 and §8.1 for source URLs and the reasoning behind each choice (descriptive
User-Agent for SEC, batch API for GLEIF entities instead of the 476 MB full file).

Run directly with ``uv run fetch_sources.py`` -- the inline metadata below gives it
its own throwaway dependency set, deliberately outside the monorepo's uv workspace
(this directory is local-only tooling, see plan §8).
"""

# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pandas>=2.2",
#     "requests>=2.32",
# ]
# ///

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]  # isolated script deps, no pandas-stubs
import requests

CACHE_DIR = Path(__file__).resolve().parent / ".cache"

# SEC blocks requests with no descriptive User-Agent (plain fetches get 403).
SEC_USER_AGENT = "context-ontology-accelerator demo-data-build (<ADMIN_EMAIL>)"

SERIES_CLASS_URL = (
    "https://www.sec.gov/files/investment/data/other/investment-company-series-and-class-information/"
    "investment_company_series_class.csv"
)

# N-PORT is filed quarterly by every reporting fund, so one quarter's zip gives a
# holdings snapshot across the whole American Century family (verified: 78 of the
# 129 AC series filed N-PORT in 2026q2 -- the rest are money-market/other filers
# on a different form, or simply didn't file that specific quarter).
NPORT_QUARTER = "2026q2"
NPORT_URL = f"https://www.sec.gov/files/dera/data/form-n-port-data-sets/{NPORT_QUARTER}_nport.zip"

# N-CEN, by contrast, is an ANNUAL filing -- each registrant files once a year, on
# its own fiscal-year clock, so a single quarterly zip only catches whichever
# registrants happen to have a fiscal year end in that quarter. Verified against
# the real data: of AC's 15 registrant CIKs, only 3 appear in 2026q2_ncen.zip.
# This 8-quarter window is the empirically-verified minimum that catches all 15
# registrants' most recent N-CEN filing as of 2026Q2 -- build_dataset.py then
# dedupes to each registrant's single latest accession across the window.
NCEN_QUARTERS: tuple[str, ...] = (
    "2024q3",
    "2024q4",
    "2025q1",
    "2025q2",
    "2025q3",
    "2025q4",
    "2026q1",
    "2026q2",
)

GLEIF_PUBLISHES_URL = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes?format=csv"
GLEIF_LEI_RECORDS_URL = "https://api.gleif.org/api/v1/lei-records"
GLEIF_PAGE_SIZE = 200


def _download(url: str, dest: Path, *, headers: dict[str, str] | None = None) -> Path:
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return dest


def fetch_series_class() -> Path:
    """Download the SEC investment-company series/class spine CSV."""
    dest = CACHE_DIR / "investment_company_series_class.csv"
    return _download(SERIES_CLASS_URL, dest, headers={"User-Agent": SEC_USER_AGENT})


def fetch_ncen_zips() -> list[Path]:
    """Download the N-CEN structured dataset zips for every quarter in NCEN_QUARTERS."""
    return [
        _download(
            f"https://www.sec.gov/files/dera/data/form-n-cen-data-sets/{q}_ncen.zip",
            CACHE_DIR / f"{q}_ncen.zip",
            headers={"User-Agent": SEC_USER_AGENT},
        )
        for q in NCEN_QUARTERS
    ]


def fetch_nport_zip() -> Path:
    """Download the N-PORT structured dataset zip for NPORT_QUARTER (~440 MB)."""
    return _download(NPORT_URL, CACHE_DIR / f"{NPORT_QUARTER}_nport.zip", headers={"User-Agent": SEC_USER_AGENT})


def read_tsv_from_zip(zip_path: Path, member: str, *, usecols: list[str] | None = None) -> pd.DataFrame:
    """Read one ``<TABLE>.tsv`` member out of an SEC structured-dataset zip."""
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as f:
        return pd.read_csv(f, sep="\t", dtype=str, usecols=usecols, low_memory=False)


def fetch_gleif_rr_csv() -> Path:
    """Download and extract the GLEIF relationship-record (rr) golden-copy CSV."""
    extracted = CACHE_DIR / "gleif_rr.csv"
    if extracted.exists():
        return extracted

    manifest = requests.get(GLEIF_PUBLISHES_URL, timeout=60)
    manifest.raise_for_status()
    rr_url = manifest.json()["data"][0]["rr"]["full_file"]["csv"]["url"]

    zip_path = CACHE_DIR / "gleif_rr.csv.zip"
    _download(rr_url, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        inner_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(inner_name) as src, open(extracted, "wb") as dst:
            dst.write(src.read())
    return extracted


def fetch_gleif_entities(leis: list[str]) -> pd.DataFrame:
    """Batch-fetch entity attributes for ``leis`` via the GLEIF lei-records API.

    Not cached to disk keyed by LEI set (the call is cheap -- ~1 request per 200
    LEIs, unauthenticated) but individual page responses are cached under
    ``.cache/gleif_entities/`` so re-running the build after a partial failure
    doesn't re-fetch pages that already succeeded.
    """
    page_cache_dir = CACHE_DIR / "gleif_entities"
    page_cache_dir.mkdir(parents=True, exist_ok=True)

    unique_leis = sorted({lei for lei in leis if lei})
    records: list[dict] = []
    for batch_start in range(0, len(unique_leis), GLEIF_PAGE_SIZE):
        batch = unique_leis[batch_start : batch_start + GLEIF_PAGE_SIZE]
        cache_key = f"batch_{batch_start:06d}_{len(batch)}.json"
        cache_file = page_cache_dir / cache_key

        if cache_file.exists():
            payload = json.loads(cache_file.read_text())
        else:
            params = {"filter[lei]": ",".join(batch), "page[size]": str(GLEIF_PAGE_SIZE)}
            resp = requests.get(GLEIF_LEI_RECORDS_URL, params=params, timeout=60)
            resp.raise_for_status()
            payload = resp.json()
            cache_file.write_text(json.dumps(payload))

        for row in payload.get("data", []):
            attrs = row["attributes"]
            entity = attrs["entity"]
            legal_address = entity.get("legalAddress") or {}
            records.append(
                {
                    "legal_entity_id": attrs["lei"],
                    "legal_name": (entity.get("legalName") or {}).get("name"),
                    "jurisdiction": entity.get("jurisdiction"),
                    "entity_category": entity.get("category"),
                    "entity_status": entity.get("status"),
                    "country": legal_address.get("country"),
                    "city": legal_address.get("city"),
                }
            )

    columns = ["legal_entity_id", "legal_name", "jurisdiction", "entity_category", "entity_status", "country", "city"]
    return pd.DataFrame.from_records(records, columns=columns)


if __name__ == "__main__":
    print("series/class:", fetch_series_class())
    print("N-CEN zips:", fetch_ncen_zips())
    print("N-PORT zip:", fetch_nport_zip())
    print("GLEIF rr csv:", fetch_gleif_rr_csv())
