"""Filter the four sources to American Century, conform to the 18-table schema in
schema.py, mint surrogate keys, and write one Parquet file per table.

Run with ``uv run build_dataset.py``. Reads from ``.cache/`` (populated by
``fetch_sources.py``, which this script calls automatically for anything missing)
and writes to ``output/<table>/<table>.parquet``. See ../../DEMO-DATASET-PLAN.md
§5, §8.2 and Appendix A for the source -> conformed-column mapping this
implements.
"""

# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pandas>=2.2",
#     "pyarrow>=17.0",
#     "requests>=2.32",
# ]
# ///

from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path
from typing import Any

import fetch_sources as src
import pandas as pd  # type: ignore[import-untyped]  # isolated script deps, no pandas-stubs
from schema import AMERICAN_CENTURY_CIKS, TABLES_BY_NAME

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
AC_CIKS = set(AMERICAN_CENTURY_CIKS)

NULL_TOKENS = {"", "N/A", "[NULL]", "NULL", "NONE"}


# ---------------------------------------------------------------------------
# Generic TSV / value-coercion helpers
# ---------------------------------------------------------------------------


def clean_str(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return None if value.upper() in NULL_TOKENS else value


def parse_bool(value: str | None) -> bool | None:
    value = clean_str(value)
    if value is None:
        return None
    return value.strip().upper() in ("Y", "YES", "TRUE", "T", "1")


def parse_float(value: str | None) -> float | None:
    value = clean_str(value)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    f = parse_float(value)
    return None if f is None else int(f)


def parse_sec_date(value: str | None):
    """Parse an SEC bulk-data date like '12-MAY-2026' into a date, or None."""
    value = clean_str(value)
    if value is None:
        return None
    ts = pd.to_datetime(value, format="%d-%b-%Y", errors="coerce")
    return None if pd.isna(ts) else ts.date()


def read_tsv_zip(zip_path: Path, member: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        return list(csv.DictReader(text, delimiter="\t"))


def read_tsv_zip_filtered(zip_path: Path, member: str, key_column: str, keep: set[str]) -> list[dict[str, str]]:
    """Stream ``member`` out of ``zip_path``, keeping only rows whose key_column is in keep.

    Used for the N-PORT tables that are hundreds of MB across the whole industry --
    avoids materializing the full table when only a few thousand AC rows matter.
    """
    out: list[dict[str, str]] = []
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        reader = csv.reader(text, delimiter="\t")
        header = next(reader)
        idx = header.index(key_column)
        for row in reader:
            if row[idx] in keep:
                out.append(dict(zip(header, row, strict=True)))
    return out


def read_tsv_zips(zip_paths: list[Path], member: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for zp in zip_paths:
        out.extend(read_tsv_zip(zp, member))
    return out


def read_tsv_zips_filtered(zip_paths: list[Path], member: str, key_column: str, keep: set[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for zp in zip_paths:
        out.extend(read_tsv_zip_filtered(zp, member, key_column, keep))
    return out


def mint_ids(keys: set[str], prefix: str, width: int = 6) -> dict[str, str]:
    return {k: f"{prefix}{i + 1:0{width}d}" for i, k in enumerate(sorted(keys))}


def to_frame(rows: list[dict], table_name: str) -> pd.DataFrame:
    """Build a DataFrame with exactly the schema's columns, in schema order."""
    columns = TABLES_BY_NAME[table_name].column_names()
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def split_fund_id(fund_id: str) -> tuple[str, str, str] | None:
    """Split N-CEN's composite FUND_ID (accession_CIK_seriesId) into its parts.

    A minority of rows (UITs, single-series registrants reporting at the
    registrant level) carry only accession_CIK with no series id -- these can't
    be attributed to a specific fund, so callers should skip them.
    """
    parts = fund_id.split("_")
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


# ---------------------------------------------------------------------------
# A registrant-provider registry: identical dedup pattern used for
# service_provider (by LEI else name) and issuer (by LEI else name/CUSIP).
# ---------------------------------------------------------------------------


class EntityRegistry:
    """Dedups records by a key function, keeping the first-seen field values."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def register(self, key: str | None, **fields) -> str | None:
        if key is None:
            return None
        if key not in self.records:
            self.records[key] = fields
        return key

    def mint_ids(self, prefix: str, width: int = 6) -> dict[str, str]:
        return mint_ids(set(self.records), prefix, width)


def lei_or_name_key(lei: str | None, name: str | None) -> str | None:
    lei = clean_str(lei)
    if lei:
        return f"LEI::{lei}"
    name = clean_str(name)
    return f"NAME::{name.strip().upper()}" if name else None


def main() -> None:
    print("Fetching sources (cached after first run)...", file=sys.stderr)
    series_class_csv = src.fetch_series_class()
    ncen_zips = src.fetch_ncen_zips()
    nport_zip = src.fetch_nport_zip()
    gleif_rr_csv = src.fetch_gleif_rr_csv()

    tables: dict[str, pd.DataFrame] = {}

    # -----------------------------------------------------------------
    # SEC series/class spine, filtered to American Century
    # -----------------------------------------------------------------
    print("Reading series/class spine...", file=sys.stderr)
    with open(series_class_csv, encoding="utf-8", errors="replace") as f:
        series_class_rows = [row for row in csv.DictReader(f) if row["CIK"] in AC_CIKS]

    ac_fund_ids = {row["series_id"] for row in series_class_rows}

    # One row per series (dedup class-level rows down to series level).
    series_by_id: dict[str, dict] = {}
    for row in series_class_rows:
        series_by_id.setdefault(row["series_id"], row)

    # -----------------------------------------------------------------
    # registrant -- N-CEN REGISTRANT.tsv, deduped to each CIK's single
    # most recent annual filing across the 8-quarter lookback window.
    # -----------------------------------------------------------------
    print("Building registrant (N-CEN, 8-quarter lookback)...", file=sys.stderr)
    ncen_registrant_rows = [r for r in read_tsv_zips(ncen_zips, "REGISTRANT.tsv") if r["CIK"] in AC_CIKS]
    ncen_accessions_seen = {r["ACCESSION_NUMBER"] for r in ncen_registrant_rows}
    ncen_submission_rows = read_tsv_zips_filtered(ncen_zips, "SUBMISSION.tsv", "ACCESSION_NUMBER", ncen_accessions_seen)
    filing_date_by_accession = {r["ACCESSION_NUMBER"]: parse_sec_date(r["FILING_DATE"]) for r in ncen_submission_rows}

    latest_registrant_by_cik: dict[str, dict] = {}
    for row in ncen_registrant_rows:
        cik = row["CIK"]
        fd = filing_date_by_accession.get(row["ACCESSION_NUMBER"])
        current = latest_registrant_by_cik.get(cik)
        if current is None or (fd or "") > (filing_date_by_accession.get(current["ACCESSION_NUMBER"]) or ""):
            latest_registrant_by_cik[cik] = row

    latest_ncen_accessions = {r["ACCESSION_NUMBER"] for r in latest_registrant_by_cik.values()}

    registrant_rows = [
        {
            "registrant_id": r["CIK"],
            "registrant_name": clean_str(r["REGISTRANT_NAME"]),
            "legal_entity_id": clean_str(r["LEI"]),
            "city": clean_str(r["CITY"]),
            "state": clean_str(r["STATE"]),
            "country": clean_str(r["COUNTRY"]),
            "investment_company_type": clean_str(r["INVESTMENT_COMPANY_TYPE"]),
            "total_series": parse_int(r["TOTAL_SERIES"]),
            "fund_family_name": clean_str(r["FAMILY_INVESTMENT_COMPANY_NAME"]),
        }
        for r in latest_registrant_by_cik.values()
    ]
    tables["registrant"] = to_frame(registrant_rows, "registrant")

    # -----------------------------------------------------------------
    # fund -- series/class spine + N-CEN FUND_REPORTED_INFO (same latest
    # accession per registrant chosen above).
    # -----------------------------------------------------------------
    print("Building fund...", file=sys.stderr)
    ncen_fri_rows = read_tsv_zips(ncen_zips, "FUND_REPORTED_INFO.tsv")
    fund_reported_info_by_series: dict[str, dict] = {}
    for row in ncen_fri_rows:
        parts = split_fund_id(row["FUND_ID"])
        if parts is None:
            continue
        accession, _cik, series_id = parts
        if accession in latest_ncen_accessions and series_id in ac_fund_ids:
            fund_reported_info_by_series[series_id] = row

    def fund_type_of(fri: dict | None) -> str:
        if fri is None:
            return "STANDARD"
        for flag, label in (
            ("IS_ETF", "ETF"),
            ("IS_INDEX", "INDEX"),
            ("IS_TARGET_DATE", "TARGET_DATE"),
            ("IS_MONEY_MARKET", "MONEY_MARKET"),
            ("IS_FUND_OF_FUND", "FUND_OF_FUNDS"),
        ):
            if parse_bool(fri.get(flag)):
                return label
        return "STANDARD"

    fund_rows = []
    for series_id, series_row in series_by_id.items():
        fri = fund_reported_info_by_series.get(series_id)
        fund_rows.append(
            {
                "fund_id": series_id,
                "fund_name": clean_str(series_row["series_name"]),
                "registrant_id": series_row["CIK"],
                "legal_entity_id": clean_str(fri["LEI"]) if fri else None,
                "fund_type": fund_type_of(fri),
                "management_fee": parse_float(fri["MANAGEMENT_FEE"]) if fri else None,
                "net_operating_expenses": parse_float(fri["NET_OPERATING_EXPENSES"]) if fri else None,
                "nav_per_share": parse_float(fri["NAV_PER_SHARE"]) if fri else None,
                "monthly_avg_net_assets": parse_float(fri["MONTHLY_AVG_NET_ASSETS"]) if fri else None,
            }
        )
    tables["fund"] = to_frame(fund_rows, "fund")

    # -----------------------------------------------------------------
    # share_class -- series/class spine, class-level rows
    # -----------------------------------------------------------------
    print("Building share_class...", file=sys.stderr)
    share_class_rows = [
        {
            "share_class_id": row["class_id"],
            "class_name": clean_str(row["class_name"]),
            "ticker_symbol": clean_str(row["class_ticker_symbol"]),
            "fund_id": row["series_id"],
        }
        for row in series_class_rows
    ]
    tables["share_class"] = to_frame(share_class_rows, "share_class")

    # -----------------------------------------------------------------
    # N-PORT: filter to American Century's accessions for this quarter
    # -----------------------------------------------------------------
    print("Filtering N-PORT to American Century...", file=sys.stderr)
    nport_registrant_rows = [r for r in read_tsv_zip(nport_zip, "REGISTRANT.tsv") if r["CIK"] in AC_CIKS]
    nport_accessions = {r["ACCESSION_NUMBER"] for r in nport_registrant_rows}
    nport_submission_rows = [
        r for r in read_tsv_zip(nport_zip, "SUBMISSION.tsv") if r["ACCESSION_NUMBER"] in nport_accessions
    ]
    submission_by_accession = {r["ACCESSION_NUMBER"]: r for r in nport_submission_rows}
    nport_fri_rows = [
        r for r in read_tsv_zip(nport_zip, "FUND_REPORTED_INFO.tsv") if r["ACCESSION_NUMBER"] in nport_accessions
    ]

    # -----------------------------------------------------------------
    # fund_period_report
    # -----------------------------------------------------------------
    print("Building fund_period_report...", file=sys.stderr)
    fund_period_report_rows = []
    known_fund_period_report_ids: set[str] = set()
    skipped_series = {row["SERIES_ID"] for row in nport_fri_rows if row["SERIES_ID"] not in ac_fund_ids}
    if skipped_series:
        print(
            f"  note: {len(skipped_series)} series filed N-PORT this quarter but aren't in the "
            "SEC series/class spine (a static extract that lags newer share classes/funds) -- "
            "their holdings are excluded since they'd have no fund row to reference.",
            file=sys.stderr,
        )
    for row in nport_fri_rows:
        if row["SERIES_ID"] not in ac_fund_ids:
            continue
        sub = submission_by_accession.get(row["ACCESSION_NUMBER"], {})
        fund_period_report_rows.append(
            {
                "fund_period_report_id": row["ACCESSION_NUMBER"],
                "fund_id": row["SERIES_ID"],
                "period_end_date": parse_sec_date(sub.get("REPORT_ENDING_PERIOD")),
                "filing_date": parse_sec_date(sub.get("FILING_DATE")),
                "total_assets": parse_float(row["TOTAL_ASSETS"]),
                "total_liabilities": parse_float(row["TOTAL_LIABILITIES"]),
                "net_assets": parse_float(row["NET_ASSETS"]),
                "sales_flow": parse_float(row["SALES_FLOW_MON3"]),
                "redemption_flow": parse_float(row["REDEMPTION_FLOW_MON3"]),
                "reinvestment_flow": parse_float(row["REINVESTMENT_FLOW_MON3"]),
                "credit_spread_5yr_investment_grade": parse_float(row.get("CREDIT_SPREAD_5YR_INVEST")),
            }
        )
        known_fund_period_report_ids.add(row["ACCESSION_NUMBER"])
    tables["fund_period_report"] = to_frame(fund_period_report_rows, "fund_period_report")

    known_share_class_ids = {r["share_class_id"] for r in share_class_rows}

    # -----------------------------------------------------------------
    # monthly_return
    # -----------------------------------------------------------------
    print("Building monthly_return...", file=sys.stderr)
    mtr_rows = read_tsv_zip_filtered(nport_zip, "MONTHLY_TOTAL_RETURN.tsv", "ACCESSION_NUMBER", nport_accessions)
    monthly_return_rows = []
    for row in mtr_rows:
        if row["ACCESSION_NUMBER"] not in known_fund_period_report_ids:
            continue
        if row["CLASS_ID"] not in known_share_class_ids:
            continue
        monthly_return_rows.append(
            {
                "monthly_return_id": f"{row['ACCESSION_NUMBER']}_{row['MONTHLY_TOTAL_RETURN_ID']}",
                "fund_period_report_id": row["ACCESSION_NUMBER"],
                "share_class_id": row["CLASS_ID"],
                "return_month_1": parse_float(row["MONTHLY_TOTAL_RETURN1"]),
                "return_month_2": parse_float(row["MONTHLY_TOTAL_RETURN2"]),
                "return_month_3": parse_float(row["MONTHLY_TOTAL_RETURN3"]),
            }
        )
    tables["monthly_return"] = to_frame(monthly_return_rows, "monthly_return")

    # -----------------------------------------------------------------
    # service_provider, fund_adviser, fund_service_engagement -- N-CEN,
    # restricted to each registrant's single latest accession.
    # -----------------------------------------------------------------
    print("Building service_provider / fund_adviser / fund_service_engagement...", file=sys.stderr)
    providers = EntityRegistry()

    def register_provider(name, lei, *, crd=None, file_num=None, pcaob=None, state=None, country=None) -> str | None:
        key = lei_or_name_key(lei, name)
        return providers.register(
            key,
            provider_name=clean_str(name),
            legal_entity_id=clean_str(lei),
            crd_number=clean_str(crd),
            sec_file_number=clean_str(file_num),
            pcaob_number=clean_str(pcaob),
            state=clean_str(state),
            country=clean_str(country),
        )

    def fund_id_from_composite(fund_id_field: str) -> tuple[str, str] | None:
        """Return (accession, series_id) if this FUND_ID belongs to a latest-accession AC fund."""
        parts = split_fund_id(fund_id_field)
        if parts is None:
            return None
        accession, _cik, series_id = parts
        if accession in latest_ncen_accessions and series_id in ac_fund_ids:
            return accession, series_id
        return None

    fund_adviser_records: list[dict[str, Any]] = []
    for row in read_tsv_zips(ncen_zips, "ADVISER.tsv"):
        resolved = fund_id_from_composite(row["FUND_ID"])
        if resolved is None:
            continue
        _accession, series_id = resolved
        key = register_provider(
            row["ADVISER_NAME"], row["ADVISER_LEI"], crd=row["CRD_NUM"], state=row["STATE"], country=row["COUNTRY"]
        )
        fund_adviser_records.append(
            {
                "fund_id": series_id,
                "provider_key": key,
                "adviser_role": clean_str(row["ADVISER_TYPE"]),
                "is_affiliated": parse_bool(row["IS_AFFILIATED"]),
                "start_date": parse_sec_date(row.get("ADVISOR_START_DATE")),
                "terminated_date": parse_sec_date(row.get("ADVISOR_TERMINATED_DATE")),
            }
        )

    engagement_records: list[dict[str, Any]] = []

    for row in read_tsv_zips(ncen_zips, "CUSTODIAN.tsv"):
        resolved = fund_id_from_composite(row["FUND_ID"])
        if resolved is None:
            continue
        _accession, series_id = resolved
        key = register_provider(row["CUSTODIAN_NAME"], row["CUSTODIAN_LEI"], state=row["STATE"], country=row["COUNTRY"])
        engagement_records.append(
            {
                "fund_id": series_id,
                "provider_key": key,
                "service_type": "Custodian",
                "is_affiliated": parse_bool(row["IS_AFFILIATED"]),
                "custody_type": clean_str(row["CUSTODY_TYPE"]),
            }
        )

    for row in read_tsv_zips(ncen_zips, "TRANSFER_AGENT.tsv"):
        resolved = fund_id_from_composite(row["FUND_ID"])
        if resolved is None:
            continue
        _accession, series_id = resolved
        key = register_provider(
            row["TRANSFERAGENT_NAME"],
            row["TRANSFERAGENT_LEI"],
            file_num=row["FILE_NUM"],
            state=row["STATE"],
            country=row["COUNTRY"],
        )
        engagement_records.append(
            {
                "fund_id": series_id,
                "provider_key": key,
                "service_type": "Transfer Agent",
                "is_affiliated": parse_bool(row["IS_AFFILIATED"]),
                "custody_type": None,
            }
        )

    for row in read_tsv_zips(ncen_zips, "AUTHORIZED_PARTICIPANT.tsv"):
        resolved = fund_id_from_composite(row["FUND_ID"])
        if resolved is None:
            continue
        _accession, series_id = resolved
        key = register_provider(
            row["PARTICIPANT_NAME"], row["PARTICIPANT_LEI"], crd=row["CRD_NUM"], file_num=row["FILE_NUM"]
        )
        engagement_records.append(
            {
                "fund_id": series_id,
                "provider_key": key,
                "service_type": "Authorized Participant",
                "is_affiliated": None,
                "custody_type": None,
            }
        )

    # Registrant-level (not fund-level) engagements: fan out to every AC series
    # reported under that same accession via REGISTRANT_REPORTING_SERIES.
    rrs_rows = read_tsv_zips_filtered(
        ncen_zips, "REGISTRANT_REPORTING_SERIES.tsv", "ACCESSION_NUMBER", latest_ncen_accessions
    )
    series_by_accession: dict[str, list[str]] = {}
    for row in rrs_rows:
        if row["SERIES_ID"] in ac_fund_ids:
            series_by_accession.setdefault(row["ACCESSION_NUMBER"], []).append(row["SERIES_ID"])

    underwriter_rows = read_tsv_zips_filtered(
        ncen_zips, "PRINCIPAL_UNDERWRITER.tsv", "ACCESSION_NUMBER", latest_ncen_accessions
    )
    for row in underwriter_rows:
        key = register_provider(
            row["UNDERWRITER_NAME"],
            row["UNDERWRITER_LEI"],
            crd=row["CRD_NUM"],
            file_num=row["FILE_NUM"],
            state=row["STATE"],
            country=row["COUNTRY"],
        )
        for series_id in series_by_accession.get(row["ACCESSION_NUMBER"], []):
            engagement_records.append(
                {
                    "fund_id": series_id,
                    "provider_key": key,
                    "service_type": "Principal Underwriter",
                    "is_affiliated": parse_bool(row["IS_AFFILIATED"]),
                    "custody_type": None,
                }
            )

    accountant_rows = read_tsv_zips_filtered(
        ncen_zips, "PUBLIC_ACCOUNTANT.tsv", "ACCESSION_NUMBER", latest_ncen_accessions
    )
    for row in accountant_rows:
        key = register_provider(
            row["PUB_ACCOUNTANT_NAME"],
            row["PUB_ACCOUNTANT_LEI"],
            pcaob=row["PCAOB_NUM"],
            state=row["STATE"],
            country=row["COUNTRY"],
        )
        for series_id in series_by_accession.get(row["ACCESSION_NUMBER"], []):
            engagement_records.append(
                {
                    "fund_id": series_id,
                    "provider_key": key,
                    "service_type": "Public Accountant",
                    "is_affiliated": None,
                    "custody_type": None,
                }
            )

    provider_id_by_key = providers.mint_ids("SP", width=4)
    service_provider_rows = [
        {"service_provider_id": provider_id_by_key[key], **fields} for key, fields in providers.records.items()
    ]
    tables["service_provider"] = to_frame(service_provider_rows, "service_provider")

    fund_adviser_rows = [
        {
            "fund_adviser_id": f"FA{i + 1:05d}",
            "fund_id": rec["fund_id"],
            "service_provider_id": provider_id_by_key[rec["provider_key"]],
            "adviser_role": rec["adviser_role"],
            "is_affiliated": rec["is_affiliated"],
            "start_date": rec["start_date"],
            "terminated_date": rec["terminated_date"],
        }
        for i, rec in enumerate(fund_adviser_records)
        if rec["provider_key"] is not None
    ]
    tables["fund_adviser"] = to_frame(fund_adviser_rows, "fund_adviser")

    fund_service_engagement_rows = [
        {
            "fund_service_engagement_id": f"FSE{i + 1:05d}",
            "fund_id": rec["fund_id"],
            "service_provider_id": provider_id_by_key[rec["provider_key"]],
            "service_type": rec["service_type"],
            "is_affiliated": rec["is_affiliated"],
            "custody_type": rec["custody_type"],
        }
        for i, rec in enumerate(engagement_records)
        if rec["provider_key"] is not None
    ]
    tables["fund_service_engagement"] = to_frame(fund_service_engagement_rows, "fund_service_engagement")

    # -----------------------------------------------------------------
    # issuer, security, holding + 5 disjoint instrument subtypes -- N-PORT
    # -----------------------------------------------------------------
    print("Filtering N-PORT holdings...", file=sys.stderr)
    holding_src_rows = read_tsv_zip_filtered(
        nport_zip, "FUND_REPORTED_HOLDING.tsv", "ACCESSION_NUMBER", nport_accessions
    )
    holding_ids = {r["HOLDING_ID"] for r in holding_src_rows}

    identifiers_rows = read_tsv_zip_filtered(nport_zip, "IDENTIFIERS.tsv", "HOLDING_ID", holding_ids)
    identifiers_by_holding: dict[str, dict] = {}
    for row in identifiers_rows:
        entry = identifiers_by_holding.setdefault(row["HOLDING_ID"], {"isin": None, "ticker": None})
        isin = clean_str(row.get("IDENTIFIER_ISIN"))
        ticker = clean_str(row.get("IDENTIFIER_TICKER"))
        if isin and not entry["isin"]:
            entry["isin"] = isin
        if ticker and not entry["ticker"]:
            entry["ticker"] = ticker

    print("Building issuer / security / holding...", file=sys.stderr)
    issuers = EntityRegistry()
    securities = EntityRegistry()
    holding_rows: list[dict[str, Any]] = []
    holding_issuer_key: dict[str, str] = {}
    holding_security_key: dict[str, str] = {}

    for row in holding_src_rows:
        hid = row["HOLDING_ID"]
        # N-PORT always reports at least an issuer name; the fallback only
        # guards against a hypothetical blank row so this stays a str, not
        # str | None (every holding must resolve to some issuer).
        issuer_key = lei_or_name_key(row.get("ISSUER_LEI"), row.get("ISSUER_NAME")) or f"HOLDING::{hid}"
        issuers.register(
            issuer_key,
            issuer_name=clean_str(row.get("ISSUER_NAME")),
            legal_entity_id=clean_str(row.get("ISSUER_LEI")),
            issuer_type=clean_str(row.get("ISSUER_TYPE")),
            country=clean_str(row.get("INVESTMENT_COUNTRY")),
        )
        holding_issuer_key[hid] = issuer_key

        ids = identifiers_by_holding.get(hid, {})
        cusip = clean_str(row.get("ISSUER_CUSIP"))
        isin = ids.get("isin")
        if cusip:
            security_key = f"CUSIP::{cusip}"
        elif isin:
            security_key = f"ISIN::{isin}"
        else:
            security_key = f"TITLE::{issuer_key}::{clean_str(row.get('ISSUER_TITLE')) or hid}"
        securities.register(
            security_key,
            issuer_key=issuer_key,
            security_title=clean_str(row.get("ISSUER_TITLE")),
            cusip=cusip,
            isin=isin,
            ticker_symbol=ids.get("ticker"),
            asset_category=clean_str(row.get("ASSET_CAT")),
            is_restricted=parse_bool(row.get("IS_RESTRICTED_SECURITY")),
        )
        holding_security_key[hid] = security_key

    issuer_id_by_key = issuers.mint_ids("ISS", width=5)
    security_id_by_key = securities.mint_ids("SEC", width=5)

    issuer_rows = [{"issuer_id": issuer_id_by_key[key], **fields} for key, fields in issuers.records.items()]
    tables["issuer"] = to_frame(issuer_rows, "issuer")

    security_rows = [
        {
            "security_id": security_id_by_key[key],
            "issuer_id": issuer_id_by_key[fields["issuer_key"]],
            "security_title": fields["security_title"],
            "cusip": fields["cusip"],
            "isin": fields["isin"],
            "ticker_symbol": fields["ticker_symbol"],
            "asset_category": fields["asset_category"],
            "is_restricted": fields["is_restricted"],
        }
        for key, fields in securities.records.items()
    ]
    tables["security"] = to_frame(security_rows, "security")

    sec_lending_rows = read_tsv_zip_filtered(nport_zip, "SECURITIES_LENDING.tsv", "HOLDING_ID", holding_ids)
    sec_lending_by_holding = {r["HOLDING_ID"]: r for r in sec_lending_rows}

    for row in holding_src_rows:
        hid = row["HOLDING_ID"]
        lending = sec_lending_by_holding.get(hid, {})
        holding_rows.append(
            {
                "holding_id": hid,
                "fund_period_report_id": row["ACCESSION_NUMBER"],
                "security_id": security_id_by_key[holding_security_key[hid]],
                "balance": parse_float(row.get("BALANCE")),
                "balance_unit": clean_str(row.get("UNIT")),
                "currency_code": clean_str(row.get("CURRENCY_CODE")),
                "market_value": parse_float(row.get("CURRENCY_VALUE")),
                "exchange_rate": parse_float(row.get("EXCHANGE_RATE")),
                "pct_of_net_assets": parse_float(row.get("PERCENTAGE")),
                "payoff_profile": clean_str(row.get("PAYOFF_PROFILE")),
                "fair_value_level": clean_str(row.get("FAIR_VALUE_LEVEL")),
                "derivative_category": clean_str(row.get("DERIVATIVE_CAT")),
                "is_on_loan": parse_bool(lending.get("IS_LOAN_BY_FUND")),
                "loan_value": parse_float(lending.get("LOAN_VALUE")),
                "has_cash_collateral": parse_bool(lending.get("IS_CASH_COLLATERAL")),
            }
        )
    # fund_period_report_id must reference a row we actually kept above.
    holding_rows = [r for r in holding_rows if r["fund_period_report_id"] in known_fund_period_report_ids]
    tables["holding"] = to_frame(holding_rows, "holding")

    kept_holding_ids = {r["holding_id"] for r in holding_rows}

    print("Building the 5 disjoint instrument-subtype tables...", file=sys.stderr)

    # N-PORT's own schema is not fully disjoint in practice: every repurchase
    # agreement and non-FX swap holding *also* gets a DEBT_SECURITY reference-
    # instrument row (verified: 100% of REPURCHASE_AGREEMENT and
    # NONFOREIGN_EXCHANGE_SWAP holding_ids also appear in DEBT_SECURITY.tsv).
    # Build the four more-specific subtypes first and let debt_holding defer to
    # them, so the five subtype tables stay disjoint the way the plan intends.
    repo_rows = [
        {
            "holding_id": r["HOLDING_ID"],
            "transaction_type": clean_str(r.get("TRANSACTION_TYPE")),
            "is_cleared": parse_bool(r.get("IS_CLEARED")),
            "central_counterparty": clean_str(r.get("CENTRAL_COUNTER_PARTY")),
            "is_triparty": parse_bool(r.get("IS_TRIPARTY")),
            "repurchase_rate": parse_float(r.get("REPURCHASE_RATE")),
            "maturity_date": parse_sec_date(r.get("MATURITY_DATE")),
        }
        for r in read_tsv_zip_filtered(nport_zip, "REPURCHASE_AGREEMENT.tsv", "HOLDING_ID", kept_holding_ids)
    ]
    tables["repurchase_agreement_holding"] = to_frame(repo_rows, "repurchase_agreement_holding")

    fwd_rows = [
        {
            "holding_id": r["HOLDING_ID"],
            "currency_sold": clean_str(r.get("DESC_CURRENCY_SOLD")),
            "currency_sold_amount": parse_float(r.get("CURRENCY_SOLD_AMOUNT")),
            "currency_purchased": clean_str(r.get("DESC_CURRENCY_PURCHASED")),
            "currency_purchased_amount": parse_float(r.get("CURRENCY_PURCHASED_AMOUNT")),
            "settlement_date": parse_sec_date(r.get("SETTLEMENT_DATE")),
            "unrealized_appreciation": parse_float(r.get("UNREALIZED_APPRECIATION")),
        }
        for r in read_tsv_zip_filtered(nport_zip, "FWD_FOREIGNCUR_CONTRACT_SWAP.tsv", "HOLDING_ID", kept_holding_ids)
    ]
    tables["forward_currency_holding"] = to_frame(fwd_rows, "forward_currency_holding")

    swap_rows = [
        {
            "holding_id": r["HOLDING_ID"],
            "swap_type": clean_str(r.get("SWAP_FLAG")),
            "termination_date": parse_sec_date(r.get("TERMINATION_DATE")),
            "notional_amount": parse_float(r.get("NOTIONAL_AMOUNT")),
            "upfront_payment": parse_float(r.get("UPFRONT_PAYMENT")),
            "upfront_receipt": parse_float(r.get("UPFRONT_RECEIPT")),
            "receipt_rate_type": clean_str(r.get("FIXED_OR_FLOATING_RECEIPT")),
            "payment_rate_type": clean_str(r.get("FIXED_OR_FLOATING_PAYMENT")),
            "unrealized_appreciation": parse_float(r.get("UNREALIZED_APPRECIATION")),
        }
        for r in read_tsv_zip_filtered(nport_zip, "NONFOREIGN_EXCHANGE_SWAP.tsv", "HOLDING_ID", kept_holding_ids)
    ]
    tables["swap_holding"] = to_frame(swap_rows, "swap_holding")

    option_rows = [
        {
            "holding_id": r["HOLDING_ID"],
            "option_type": clean_str(r.get("PUT_OR_CALL")),
            "position_type": clean_str(r.get("WRITTEN_OR_PURCHASED")),
            "share_count": parse_float(r.get("SHARES_CNT")),
            "principal_amount": parse_float(r.get("PRINCIPAL_AMOUNT")),
            "exercise_price": parse_float(r.get("EXERCISE_PRICE")),
            "expiration_date": parse_sec_date(r.get("EXPIRATION_DATE")),
            "unrealized_appreciation": parse_float(r.get("UNREALIZED_APPRECIATION")),
        }
        for r in read_tsv_zip_filtered(nport_zip, "SWAPTION_OPTION_WARNT_DERIV.tsv", "HOLDING_ID", kept_holding_ids)
    ]
    tables["option_warrant_holding"] = to_frame(option_rows, "option_warrant_holding")

    other_subtype_ids = {r["holding_id"] for r in repo_rows + fwd_rows + swap_rows + option_rows}
    debt_candidate_ids = kept_holding_ids - other_subtype_ids
    debt_rows = [
        {
            "holding_id": r["HOLDING_ID"],
            "maturity_date": parse_sec_date(r.get("MATURITY_DATE")),
            "coupon_type": clean_str(r.get("COUPON_TYPE")),
            "annualized_rate": parse_float(r.get("ANNUALIZED_RATE")),
            "is_in_default": parse_bool(r.get("IS_DEFAULT")),
            "is_mandatory_convertible": parse_bool(r.get("IS_CONVTIBLE_MANDATORY")),
        }
        for r in read_tsv_zip_filtered(nport_zip, "DEBT_SECURITY.tsv", "HOLDING_ID", debt_candidate_ids)
    ]
    tables["debt_holding"] = to_frame(debt_rows, "debt_holding")

    # -----------------------------------------------------------------
    # legal_entity, legal_entity_relationship -- GLEIF
    # -----------------------------------------------------------------
    print("Resolving legal entities via GLEIF...", file=sys.stderr)
    known_leis: set[str] = set()
    for df in (tables["registrant"], tables["fund"], tables["service_provider"], tables["issuer"]):
        known_leis.update(lei for lei in df["legal_entity_id"].dropna().tolist() if lei)

    legal_entity_df = src.fetch_gleif_entities(sorted(known_leis))

    print("Filtering GLEIF relationship-record file...", file=sys.stderr)
    RELATIONSHIP_TYPES = {"IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY"}
    rr_rows: list[dict] = []
    with open(gleif_rr_csv, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Relationship.RelationshipType"] not in RELATIONSHIP_TYPES:
                continue
            # Only the parent chain OUT of our own entities -- NOT every other
            # relationship touching a shared parent (e.g. a custodian bank's LEI
            # is also the ultimate parent of tens of thousands of unrelated
            # subsidiaries; matching on "end in known_leis" pulled in all of them).
            if row["Relationship.StartNode.NodeID"] in known_leis:
                rr_rows.append(row)

    referenced_leis = {r["Relationship.StartNode.NodeID"] for r in rr_rows} | {
        r["Relationship.EndNode.NodeID"] for r in rr_rows
    }
    missing_leis = sorted(referenced_leis - known_leis)
    if missing_leis:
        print(f"Fetching {len(missing_leis)} additional parent LEIs referenced by relationships...", file=sys.stderr)
        legal_entity_df = pd.concat([legal_entity_df, src.fetch_gleif_entities(missing_leis)], ignore_index=True)
        known_leis.update(missing_leis)

    legal_entity_df = legal_entity_df.drop_duplicates(subset="legal_entity_id").reset_index(drop=True)
    tables["legal_entity"] = to_frame(legal_entity_df.to_dict("records"), "legal_entity")

    resolved_leis = set(legal_entity_df["legal_entity_id"])
    legal_entity_relationship_rows = [
        {
            "legal_entity_relationship_id": f"LER{i + 1:05d}",
            "legal_entity_id": r["Relationship.StartNode.NodeID"],
            "parent_legal_entity_id": r["Relationship.EndNode.NodeID"],
            "relationship_type": r["Relationship.RelationshipType"],
            "relationship_status": r["Relationship.RelationshipStatus"],
        }
        for i, r in enumerate(rr_rows)
        if r["Relationship.StartNode.NodeID"] in resolved_leis and r["Relationship.EndNode.NodeID"] in resolved_leis
    ]
    tables["legal_entity_relationship"] = to_frame(legal_entity_relationship_rows, "legal_entity_relationship")

    # -----------------------------------------------------------------
    # Write Parquet, one file per table, matching load.sh's S3 layout.
    # -----------------------------------------------------------------
    print("Writing Parquet...", file=sys.stderr)
    for name, df in tables.items():
        table_dir = OUTPUT_DIR / name
        table_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(table_dir / f"{name}.parquet", index=False)
        print(f"  {name}: {len(df)} rows -> {table_dir / f'{name}.parquet'}", file=sys.stderr)

    missing_tables = set(TABLES_BY_NAME) - set(tables)
    if missing_tables:
        sys.exit(f"error: no rows built for {sorted(missing_tables)}")


if __name__ == "__main__":
    main()
