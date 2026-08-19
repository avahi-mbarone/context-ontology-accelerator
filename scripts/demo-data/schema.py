"""Single source of truth for the American Century demo dataset's 18-table schema.

See ../../DEMO-DATASET-PLAN.md §5 and Appendix A for the design rationale and the
source -> conformed-column mapping. Every table name is its PK column's stem
(``holding_id -> holding.holding_id``) so the Pass-2 FK inferrer's naming-convention
heuristic fires, and every PK is a single-column surrogate so subtype detection
(PK-sharing) and FK inference both apply cleanly.

``build_dataset.py`` imports ``TABLES`` to know what to build; ``glue_tables.py``
imports it to emit one Glue create-table input per table. Neither hardcodes a
column list of its own -- add or change a column here and both pick it up.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    name: str
    glue_type: str  # Athena/Glue type: string, int, bigint, double, boolean, date
    comment: str


@dataclass(frozen=True)
class ForeignKey:
    column: str
    references_table: str
    references_column: str


@dataclass(frozen=True)
class Table:
    name: str
    comment: str
    primary_key: str
    columns: tuple[Column, ...]
    foreign_keys: tuple[ForeignKey, ...] = field(default_factory=tuple)

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


# ---------------------------------------------------------------------------
# Fund spine
# ---------------------------------------------------------------------------

REGISTRANT = Table(
    name="registrant",
    comment="An American Century registrant (investment company) filing with the SEC, keyed by CIK.",
    primary_key="registrant_id",
    columns=(
        Column("registrant_id", "string", "SEC Central Index Key (CIK) of the registrant."),
        Column("registrant_name", "string", "Legal name of the registrant."),
        Column("legal_entity_id", "string", "Legal Entity Identifier (LEI) of the registrant."),
        Column("city", "string", "Registrant's city of record."),
        Column("state", "string", "Registrant's state of record (ISO US-XX code)."),
        Column("country", "string", "Registrant's country of record (ISO alpha-2)."),
        Column("investment_company_type", "string", "SEC investment company type code, e.g. N-1A."),
        Column("total_series", "int", "Total number of series (funds) reported under this registrant."),
        Column("fund_family_name", "string", "Marketing name of the fund family, e.g. AMERICAN CENTURY."),
    ),
)

FUND = Table(
    name="fund",
    comment="A single American Century fund (SEC 'series').",
    primary_key="fund_id",
    columns=(
        Column("fund_id", "string", "SEC series identifier (SERIES_ID), e.g. S000012345."),
        Column("fund_name", "string", "Fund (series) name."),
        Column("registrant_id", "string", "CIK of the owning registrant."),
        Column("legal_entity_id", "string", "Legal Entity Identifier (LEI) of the fund, where reported."),
        Column(
            "fund_type",
            "string",
            "Fund type derived from N-CEN flags: ETF, INDEX, TARGET_DATE, MONEY_MARKET, FUND_OF_FUNDS, or STANDARD.",
        ),
        Column("management_fee", "double", "Contractual management fee, percent of net assets."),
        Column("net_operating_expenses", "double", "Net operating expense ratio, percent of net assets."),
        Column("nav_per_share", "double", "Net asset value per share as of the N-CEN reporting period."),
        Column("monthly_avg_net_assets", "double", "Average net assets over the N-CEN reporting period, USD."),
    ),
    foreign_keys=(ForeignKey("registrant_id", "registrant", "registrant_id"),),
)

SHARE_CLASS = Table(
    name="share_class",
    comment="A share class of an American Century fund.",
    primary_key="share_class_id",
    columns=(
        Column("share_class_id", "string", "SEC class identifier (CLASS_ID), e.g. C000012345."),
        Column("class_name", "string", "Share class name, e.g. Investor Class."),
        Column("ticker_symbol", "string", "Exchange ticker symbol for the share class, where listed."),
        Column("fund_id", "string", "Series identifier (fund) this share class belongs to."),
    ),
    foreign_keys=(ForeignKey("fund_id", "fund", "fund_id"),),
)

FUND_PERIOD_REPORT = Table(
    name="fund_period_report",
    comment="One N-PORT monthly report period for a fund.",
    primary_key="fund_period_report_id",
    columns=(
        Column("fund_period_report_id", "string", "N-PORT filing accession number."),
        Column("fund_id", "string", "Series identifier (fund) this report covers."),
        Column("period_end_date", "date", "Last day of the reporting period."),
        Column("filing_date", "date", "Date the N-PORT filing was submitted to the SEC."),
        Column("total_assets", "double", "Total fund assets as of period end, USD."),
        Column("total_liabilities", "double", "Total fund liabilities as of period end, USD."),
        Column("net_assets", "double", "Net assets as of period end, USD."),
        Column("sales_flow", "double", "Third-month gross sales flow, USD."),
        Column("redemption_flow", "double", "Third-month gross redemption flow, USD."),
        Column("reinvestment_flow", "double", "Third-month reinvestment flow, USD."),
        Column(
            "credit_spread_5yr_investment_grade",
            "double",
            "Fund-level weighted average 5-year credit spread duration for investment-grade debt.",
        ),
    ),
    foreign_keys=(ForeignKey("fund_id", "fund", "fund_id"),),
)

MONTHLY_RETURN = Table(
    name="monthly_return",
    comment="A share class's monthly total return, as reported on N-PORT.",
    primary_key="monthly_return_id",
    columns=(
        Column("monthly_return_id", "string", "Surrogate key: accession number + N-PORT MONTHLY_TOTAL_RETURN_ID."),
        Column("fund_period_report_id", "string", "N-PORT filing this return was reported on."),
        Column("share_class_id", "string", "Share class the return applies to."),
        Column("return_month_1", "double", "Total return for the first month of the quarter, percent."),
        Column("return_month_2", "double", "Total return for the second month of the quarter, percent."),
        Column("return_month_3", "double", "Total return for the third month of the quarter, percent."),
    ),
    foreign_keys=(
        ForeignKey("fund_period_report_id", "fund_period_report", "fund_period_report_id"),
        ForeignKey("share_class_id", "share_class", "share_class_id"),
    ),
)

# ---------------------------------------------------------------------------
# Service providers -- from N-CEN
# ---------------------------------------------------------------------------

SERVICE_PROVIDER = Table(
    name="service_provider",
    comment="A firm providing a service to one or more American Century funds (adviser, custodian, "
    "transfer agent, underwriter, auditor, or authorized participant), deduplicated by LEI.",
    primary_key="service_provider_id",
    columns=(
        Column("service_provider_id", "string", "Surrogate key, minted on dedup by LEI (or normalized name)."),
        Column("provider_name", "string", "Provider's legal name."),
        Column("legal_entity_id", "string", "Legal Entity Identifier (LEI) of the provider, where reported."),
        Column("crd_number", "string", "FINRA Central Registration Depository number, where applicable."),
        Column("sec_file_number", "string", "SEC file number, where applicable."),
        Column("pcaob_number", "string", "PCAOB registration number, for public accountants."),
        Column("state", "string", "Provider's state of record (ISO US-XX code)."),
        Column("country", "string", "Provider's country of record (ISO alpha-2)."),
    ),
    foreign_keys=(ForeignKey("legal_entity_id", "legal_entity", "legal_entity_id"),),
)

FUND_ADVISER = Table(
    name="fund_adviser",
    comment="An adviser or sub-adviser engagement between a fund and a service provider.",
    primary_key="fund_adviser_id",
    columns=(
        Column("fund_adviser_id", "string", "Surrogate key."),
        Column("fund_id", "string", "Fund being advised."),
        Column("service_provider_id", "string", "Adviser firm."),
        Column("adviser_role", "string", "Role reported on N-CEN, e.g. Advisor, Subadvisor, Terminated Advisor."),
        Column("is_affiliated", "boolean", "Whether the adviser is affiliated with the fund's registrant."),
        Column("start_date", "date", "Date the adviser engagement started, where reported."),
        Column("terminated_date", "date", "Date the adviser engagement terminated, where reported."),
    ),
    foreign_keys=(
        ForeignKey("fund_id", "fund", "fund_id"),
        ForeignKey("service_provider_id", "service_provider", "service_provider_id"),
    ),
)

FUND_SERVICE_ENGAGEMENT = Table(
    name="fund_service_engagement",
    comment="A non-advisory service engagement between a fund and a service provider "
    "(custodian, transfer agent, principal underwriter, public accountant, or authorized participant).",
    primary_key="fund_service_engagement_id",
    columns=(
        Column("fund_service_engagement_id", "string", "Surrogate key."),
        Column("fund_id", "string", "Fund receiving the service."),
        Column("service_provider_id", "string", "Service provider firm."),
        Column(
            "service_type",
            "string",
            "Type of service: Custodian, Transfer Agent, Principal Underwriter, Public Accountant, "
            "or Authorized Participant.",
        ),
        Column("is_affiliated", "boolean", "Whether the provider is affiliated with the fund's registrant."),
        Column("custody_type", "string", "Custody arrangement type, for custodian engagements only."),
    ),
    foreign_keys=(
        ForeignKey("fund_id", "fund", "fund_id"),
        ForeignKey("service_provider_id", "service_provider", "service_provider_id"),
    ),
)

# ---------------------------------------------------------------------------
# Holdings + instrument subtypes -- from N-PORT
# ---------------------------------------------------------------------------

ISSUER = Table(
    name="issuer",
    comment="An issuer of a security held by an American Century fund, deduplicated by LEI/name.",
    primary_key="issuer_id",
    columns=(
        Column("issuer_id", "string", "Surrogate key, minted on dedup by ISSUER_LEI then ISSUER_NAME."),
        Column("issuer_name", "string", "Issuer's name as reported on N-PORT."),
        Column("legal_entity_id", "string", "Legal Entity Identifier (LEI) of the issuer, where reported."),
        Column("issuer_type", "string", "N-PORT issuer type code, e.g. CORP, US-GOV, MUN."),
        Column("country", "string", "Issuer's country of investment (ISO alpha-2)."),
    ),
    foreign_keys=(ForeignKey("legal_entity_id", "legal_entity", "legal_entity_id"),),
)

SECURITY = Table(
    name="security",
    comment="A specific security issued by an issuer and held by an American Century fund, deduplicated by CUSIP/ISIN.",
    primary_key="security_id",
    columns=(
        Column("security_id", "string", "Surrogate key, minted on dedup by CUSIP then ISIN."),
        Column("issuer_id", "string", "Issuer of this security."),
        Column("security_title", "string", "Security title/description as reported on N-PORT."),
        Column("cusip", "string", "CUSIP identifier, where reported."),
        Column("isin", "string", "ISIN identifier, where reported."),
        Column("ticker_symbol", "string", "Exchange ticker symbol, where reported."),
        Column("asset_category", "string", "N-PORT asset category code, e.g. DBT, EC, DFE."),
        Column("is_restricted", "boolean", "Whether the security is restricted."),
    ),
    foreign_keys=(ForeignKey("issuer_id", "issuer", "issuer_id"),),
)

HOLDING = Table(
    name="holding",
    comment="A single position held by a fund as of a reporting period, as reported on N-PORT. "
    "Securities-lending fields are folded in here rather than a subtype table, since they apply "
    "to every holding row rather than a disjoint subset.",
    primary_key="holding_id",
    columns=(
        Column("holding_id", "string", "N-PORT HOLDING_ID."),
        Column("fund_period_report_id", "string", "N-PORT filing this holding was reported on."),
        Column("security_id", "string", "Security held."),
        Column("balance", "double", "Quantity held, in the reported unit."),
        Column("balance_unit", "string", "Unit the balance is denominated in, e.g. NS (shares), PA (principal)."),
        Column("currency_code", "string", "ISO currency code of the market value."),
        Column("market_value", "double", "Fair value of the position, in currency_code."),
        Column("exchange_rate", "double", "Exchange rate to USD, where the position is non-USD."),
        Column("pct_of_net_assets", "double", "Position's percent of the fund's net assets."),
        Column("payoff_profile", "string", "Payoff profile for derivatives, e.g. Long, Short, N/A."),
        Column("fair_value_level", "string", "ASC 820 fair value hierarchy level (1, 2, or 3)."),
        Column("derivative_category", "string", "Derivative category code, where applicable."),
        Column("is_on_loan", "boolean", "Whether the position was on loan as of period end."),
        Column("loan_value", "double", "Value of the position on loan, USD."),
        Column("has_cash_collateral", "boolean", "Whether the loan is collateralized with cash."),
    ),
    foreign_keys=(
        ForeignKey("fund_period_report_id", "fund_period_report", "fund_period_report_id"),
        ForeignKey("security_id", "security", "security_id"),
    ),
)

DEBT_HOLDING = Table(
    name="debt_holding",
    comment="Debt-security-specific detail for a holding. PK-shares holding_id with holding, "
    "one of five disjoint instrument subtypes.",
    primary_key="holding_id",
    columns=(
        Column("holding_id", "string", "Holding this debt detail belongs to (also this table's PK)."),
        Column("maturity_date", "date", "Debt instrument maturity date."),
        Column("coupon_type", "string", "Coupon type, e.g. Fixed, Floating, None."),
        Column("annualized_rate", "double", "Annualized interest rate, percent."),
        Column("is_in_default", "boolean", "Whether the issuer is in default on this instrument."),
        Column("is_mandatory_convertible", "boolean", "Whether the instrument is a mandatory convertible."),
    ),
    foreign_keys=(ForeignKey("holding_id", "holding", "holding_id"),),
)

REPURCHASE_AGREEMENT_HOLDING = Table(
    name="repurchase_agreement_holding",
    comment="Repurchase-agreement-specific detail for a holding. PK-shares holding_id with holding, "
    "one of five disjoint instrument subtypes.",
    primary_key="holding_id",
    columns=(
        Column("holding_id", "string", "Holding this repo detail belongs to (also this table's PK)."),
        Column("transaction_type", "string", "Repurchase or Reverse Repurchase."),
        Column("is_cleared", "boolean", "Whether the transaction is centrally cleared."),
        Column("central_counterparty", "string", "Central counterparty name, where cleared."),
        Column("is_triparty", "boolean", "Whether the transaction is tri-party."),
        Column("repurchase_rate", "double", "Repurchase rate, percent."),
        Column("maturity_date", "date", "Repo maturity date."),
    ),
    foreign_keys=(ForeignKey("holding_id", "holding", "holding_id"),),
)

FORWARD_CURRENCY_HOLDING = Table(
    name="forward_currency_holding",
    comment="Forward-currency-contract-specific detail for a holding. PK-shares holding_id with "
    "holding, one of five disjoint instrument subtypes.",
    primary_key="holding_id",
    columns=(
        Column("holding_id", "string", "Holding this forward-currency detail belongs to (also this table's PK)."),
        Column("currency_sold", "string", "Currency sold, ISO code."),
        Column("currency_sold_amount", "double", "Amount of currency sold."),
        Column("currency_purchased", "string", "Currency purchased, ISO code."),
        Column("currency_purchased_amount", "double", "Amount of currency purchased."),
        Column("settlement_date", "date", "Contract settlement date."),
        Column("unrealized_appreciation", "double", "Unrealized appreciation/(depreciation), USD."),
    ),
    foreign_keys=(ForeignKey("holding_id", "holding", "holding_id"),),
)

SWAP_HOLDING = Table(
    name="swap_holding",
    comment="Non-foreign-exchange-swap-specific detail for a holding. PK-shares holding_id with "
    "holding, one of five disjoint instrument subtypes.",
    primary_key="holding_id",
    columns=(
        Column("holding_id", "string", "Holding this swap detail belongs to (also this table's PK)."),
        Column("swap_type", "string", "Cleared/uncleared swap flag as reported (SWAP_FLAG)."),
        Column("termination_date", "date", "Swap termination date."),
        Column("notional_amount", "double", "Notional amount of the swap."),
        Column("upfront_payment", "double", "Upfront payment made, USD."),
        Column("upfront_receipt", "double", "Upfront payment received, USD."),
        Column("receipt_rate_type", "string", "Fixed or Floating rate on the receipt leg."),
        Column("payment_rate_type", "string", "Fixed or Floating rate on the payment leg."),
        Column("unrealized_appreciation", "double", "Unrealized appreciation/(depreciation), USD."),
    ),
    foreign_keys=(ForeignKey("holding_id", "holding", "holding_id"),),
)

OPTION_WARRANT_HOLDING = Table(
    name="option_warrant_holding",
    comment="Option/warrant/swaption-specific detail for a holding. PK-shares holding_id with "
    "holding, one of five disjoint instrument subtypes.",
    primary_key="holding_id",
    columns=(
        Column("holding_id", "string", "Holding this option detail belongs to (also this table's PK)."),
        Column("option_type", "string", "Put or Call."),
        Column("position_type", "string", "Written or Purchased."),
        Column("share_count", "double", "Number of shares underlying the option, where applicable."),
        Column("principal_amount", "double", "Principal amount underlying the option, where applicable."),
        Column("exercise_price", "double", "Exercise/strike price."),
        Column("expiration_date", "date", "Option expiration date."),
        Column("unrealized_appreciation", "double", "Unrealized appreciation/(depreciation), USD."),
    ),
    foreign_keys=(ForeignKey("holding_id", "holding", "holding_id"),),
)

# ---------------------------------------------------------------------------
# Legal entity graph -- from GLEIF
# ---------------------------------------------------------------------------

LEGAL_ENTITY = Table(
    name="legal_entity",
    comment="A legal entity registered in the Global LEI System (GLEIF), referenced by American "
    "Century registrants, funds, issuers, and service providers.",
    primary_key="legal_entity_id",
    columns=(
        Column("legal_entity_id", "string", "Legal Entity Identifier (LEI), a 20-character GLEIF code."),
        Column("legal_name", "string", "Entity's registered legal name."),
        Column("jurisdiction", "string", "Entity's jurisdiction of registration (ISO code)."),
        Column("entity_category", "string", "GLEIF entity category, e.g. FUND, GENERAL, BRANCH."),
        Column("entity_status", "string", "GLEIF registration status, e.g. ACTIVE, INACTIVE."),
        Column("country", "string", "Entity's legal address country (ISO alpha-2)."),
        Column("city", "string", "Entity's legal address city."),
    ),
)

LEGAL_ENTITY_RELATIONSHIP = Table(
    name="legal_entity_relationship",
    comment="A direct or ultimate parent relationship between two legal entities, from the GLEIF "
    "relationship record (rr) file. Self-referencing hierarchy over legal_entity.",
    primary_key="legal_entity_relationship_id",
    columns=(
        Column("legal_entity_relationship_id", "string", "Surrogate key."),
        Column("legal_entity_id", "string", "Child entity in the relationship."),
        Column("parent_legal_entity_id", "string", "Parent entity in the relationship."),
        Column(
            "relationship_type",
            "string",
            "IS_DIRECTLY_CONSOLIDATED_BY or IS_ULTIMATELY_CONSOLIDATED_BY.",
        ),
        Column("relationship_status", "string", "GLEIF relationship status, e.g. ACTIVE, INACTIVE."),
    ),
    foreign_keys=(
        ForeignKey("legal_entity_id", "legal_entity", "legal_entity_id"),
        ForeignKey("parent_legal_entity_id", "legal_entity", "legal_entity_id"),
    ),
)

TABLES: tuple[Table, ...] = (
    REGISTRANT,
    FUND,
    SHARE_CLASS,
    FUND_PERIOD_REPORT,
    MONTHLY_RETURN,
    SERVICE_PROVIDER,
    FUND_ADVISER,
    FUND_SERVICE_ENGAGEMENT,
    ISSUER,
    SECURITY,
    HOLDING,
    DEBT_HOLDING,
    REPURCHASE_AGREEMENT_HOLDING,
    FORWARD_CURRENCY_HOLDING,
    SWAP_HOLDING,
    OPTION_WARRANT_HOLDING,
    LEGAL_ENTITY,
    LEGAL_ENTITY_RELATIONSHIP,
)

TABLES_BY_NAME: dict[str, Table] = {t.name: t for t in TABLES}

# American Century CIKs, verified against the SEC series/class file (see plan §4).
# Adding peer fund families later is a one-line change here.
AMERICAN_CENTURY_CIKS: tuple[str, ...] = (
    "0000100334",
    "0000717316",
    "0000746458",
    "0000757928",
    "0000773674",
    "0000814680",
    "0000827060",
    "0000872825",
    "0000880268",
    "0000908186",
    "0000908406",
    "0000924211",
    "0001124155",
    "0001293210",
    "0001353176",
)

GLUE_DATABASE_NAME = "coa_dev_asset_mgmt"
S3_PREFIX = "american-century"
