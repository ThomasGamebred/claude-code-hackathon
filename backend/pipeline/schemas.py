"""DuckDB DDL and source contracts for the three lakehouse zones.

The raw zone holds one table per source with verbatim values plus lineage.
The conformed zone holds a single canonical customer table plus a reject sink.
The curated zone holds the golden master, cross-reference, audit, and review queue.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceContract:
    """Recorded shape of a source feed used for schema-drift checks."""

    name: str
    source_file: str
    columns: tuple[str, ...]
    delimiter: str | None = None
    encoding: str | None = None


CONTRACTS: tuple[SourceContract, ...] = (
    SourceContract(
        name="acq_northwind",
        source_file="acq_northwind/legacy_customers.txt",
        columns=("CUSTNO", "CUSTNAME", "ADDR1", "CITY", "ST", "ZIP", "PHONE", "DTADDED", "DTBIRTH", "STATUS"),
        delimiter="|",
        encoding="utf-8",
    ),
    SourceContract(
        name="acq_rheinland",
        source_file="acq_rheinland/kunden.csv",
        columns=("Kundennr", "Name", "Strasse", "PLZ", "Ort", "Telefon", "Email", "Geburtsdatum", "Umsatz", "Newsletter"),
        delimiter=";",
        encoding="mixed",
    ),
    SourceContract(
        name="acq_sunset",
        source_file="acq_sunset/catalog_customers.csv",
        columns=("acct", "name", "address", "city", "st", "zip", "phone", "signup_dt", "email", "notes"),
        delimiter=",",
        encoding="utf-8-lossy",
    ),
    SourceContract(
        name="crm",
        source_file="crm/crm_contacts.csv",
        columns=(
            "contact_id", "account_name", "full_name", "email", "phone",
            "mailing_street", "mailing_city", "mailing_state", "mailing_zip",
            "date_of_birth", "lead_source", "created_date",
        ),
        delimiter=",",
        encoding="utf-8-sig",
    ),
    SourceContract(
        name="ecommerce",
        source_file="ecommerce/customers.json",
        columns=(
            "customer_id", "first_name", "last_name", "email", "phone", "created_at",
            "line1", "city", "region", "postal_code", "country",
            "marketing_opt_in", "total_orders",
        ),
        delimiter=None,
        encoding="utf-8",
    ),
    SourceContract(
        name="loyalty",
        source_file="loyalty/loyalty_members.csv",
        columns=(
            "member_id", "full_name", "email", "phone", "tier", "points_balance",
            "enrolled_at", "birth_date", "home_store", "pos_customer_id",
        ),
        delimiter=",",
        encoding="utf-8",
    ),
    SourceContract(
        name="pos",
        source_file="pos/pos_export_2023-11.csv",
        columns=(
            "CUST_ID", "NAME", "PHONE", "EMAIL", "ADDR", "CITY", "STATE", "ZIP",
            "DOB", "LAST_TXN_DATE", "LIFETIME_SPEND",
        ),
        delimiter=",",
        encoding="utf-8-lossy",
    ),
)


# Per-source raw DDL. Every raw table carries the same five lineage columns.
RAW_DDL: str = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS conformed;
CREATE SCHEMA IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS raw.acq_northwind (
    CUSTNO     VARCHAR,
    CUSTNAME   VARCHAR,
    ADDR1      VARCHAR,
    CITY       VARCHAR,
    ST         VARCHAR,
    ZIP        VARCHAR,
    PHONE      VARCHAR,
    DTADDED    VARCHAR,
    DTBIRTH    VARCHAR,
    STATUS     VARCHAR,
    _source        VARCHAR,
    _source_file   VARCHAR,
    _source_row    BIGINT,
    _ingested_at   TIMESTAMP,
    _raw_payload   VARCHAR
);

CREATE TABLE IF NOT EXISTS raw.acq_rheinland (
    Kundennr      VARCHAR,
    Name          VARCHAR,
    Strasse       VARCHAR,
    PLZ           VARCHAR,
    Ort           VARCHAR,
    Telefon       VARCHAR,
    Email         VARCHAR,
    Geburtsdatum  VARCHAR,
    Umsatz        VARCHAR,
    Newsletter    VARCHAR,
    _encoding_fixed BOOLEAN,
    _source        VARCHAR,
    _source_file   VARCHAR,
    _source_row    BIGINT,
    _ingested_at   TIMESTAMP,
    _raw_payload   VARCHAR
);

CREATE TABLE IF NOT EXISTS raw.acq_sunset (
    acct      VARCHAR,
    name      VARCHAR,
    address   VARCHAR,
    city      VARCHAR,
    st        VARCHAR,
    zip       VARCHAR,
    phone     VARCHAR,
    signup_dt VARCHAR,
    email     VARCHAR,
    notes     VARCHAR,
    _source        VARCHAR,
    _source_file   VARCHAR,
    _source_row    BIGINT,
    _ingested_at   TIMESTAMP,
    _raw_payload   VARCHAR
);

CREATE TABLE IF NOT EXISTS raw.crm (
    contact_id     VARCHAR,
    account_name   VARCHAR,
    full_name      VARCHAR,
    email          VARCHAR,
    phone          VARCHAR,
    mailing_street VARCHAR,
    mailing_city   VARCHAR,
    mailing_state  VARCHAR,
    mailing_zip    VARCHAR,
    date_of_birth  VARCHAR,
    lead_source    VARCHAR,
    created_date   VARCHAR,
    _source        VARCHAR,
    _source_file   VARCHAR,
    _source_row    BIGINT,
    _ingested_at   TIMESTAMP,
    _raw_payload   VARCHAR
);

CREATE TABLE IF NOT EXISTS raw.ecommerce (
    customer_id      VARCHAR,
    first_name       VARCHAR,
    last_name        VARCHAR,
    email            VARCHAR,
    phone            VARCHAR,
    created_at       VARCHAR,
    line1            VARCHAR,
    city             VARCHAR,
    region           VARCHAR,
    postal_code      VARCHAR,
    country          VARCHAR,
    marketing_opt_in BOOLEAN,
    total_orders     INTEGER,
    _source        VARCHAR,
    _source_file   VARCHAR,
    _source_row    BIGINT,
    _ingested_at   TIMESTAMP,
    _raw_payload   VARCHAR
);

CREATE TABLE IF NOT EXISTS raw.loyalty (
    member_id        VARCHAR,
    full_name        VARCHAR,
    email            VARCHAR,
    phone            VARCHAR,
    tier             VARCHAR,
    points_balance   VARCHAR,
    enrolled_at      VARCHAR,
    birth_date       VARCHAR,
    home_store       VARCHAR,
    pos_customer_id  VARCHAR,
    _source        VARCHAR,
    _source_file   VARCHAR,
    _source_row    BIGINT,
    _ingested_at   TIMESTAMP,
    _raw_payload   VARCHAR
);

CREATE TABLE IF NOT EXISTS raw.pos (
    CUST_ID         VARCHAR,
    NAME            VARCHAR,
    PHONE           VARCHAR,
    EMAIL           VARCHAR,
    ADDR            VARCHAR,
    CITY            VARCHAR,
    STATE           VARCHAR,
    ZIP             VARCHAR,
    DOB             VARCHAR,
    LAST_TXN_DATE   VARCHAR,
    LIFETIME_SPEND  VARCHAR,
    _source        VARCHAR,
    _source_file   VARCHAR,
    _source_row    BIGINT,
    _ingested_at   TIMESTAMP,
    _raw_payload   VARCHAR
);
"""


CONFORMED_DDL: str = """
CREATE TABLE IF NOT EXISTS conformed.customer (
    _source                 VARCHAR NOT NULL,
    _source_id              VARCHAR NOT NULL,
    _source_row             BIGINT,
    _source_tz              VARCHAR,
    _encoding_lossy         BOOLEAN,
    first_name              VARCHAR,
    last_name               VARCHAR,
    full_name_normalized    VARCHAR,
    email_normalized        VARCHAR,
    phone_e164              VARCHAR,
    phone_ext               VARCHAR,
    street                  VARCHAR,
    city                    VARCHAR,
    region                  VARCHAR,
    postal_code             VARCHAR,
    country                 VARCHAR,
    birth_date              DATE,
    created_at_utc          TIMESTAMP,
    field_quality_flags     VARCHAR,
    PRIMARY KEY (_source, _source_id)
);

CREATE TABLE IF NOT EXISTS conformed._reject (
    _source         VARCHAR,
    _source_id      VARCHAR,
    _source_row     BIGINT,
    reject_field    VARCHAR,
    reject_reason   VARCHAR,
    raw_payload     VARCHAR,
    rejected_at     TIMESTAMP
);
"""


CURATED_DDL: str = """
CREATE TABLE IF NOT EXISTS curated.customer_master (
    customer_id                 VARCHAR PRIMARY KEY,
    first_name                  VARCHAR,
    first_name_source           VARCHAR,
    first_name_confidence       DOUBLE,
    last_name                   VARCHAR,
    last_name_source            VARCHAR,
    last_name_confidence        DOUBLE,
    full_name                   VARCHAR,
    full_name_source            VARCHAR,
    full_name_confidence        DOUBLE,
    email_hash                  VARCHAR,
    email_source                VARCHAR,
    email_confidence            DOUBLE,
    phone_hash                  VARCHAR,
    phone_source                VARCHAR,
    phone_confidence            DOUBLE,
    street_token                VARCHAR,
    street_source               VARCHAR,
    street_confidence           DOUBLE,
    city                        VARCHAR,
    city_source                 VARCHAR,
    region                      VARCHAR,
    region_source               VARCHAR,
    postal_code                 VARCHAR,
    postal_code_source          VARCHAR,
    country                     VARCHAR,
    country_source              VARCHAR,
    birth_date                  DATE,
    birth_date_source           VARCHAR,
    birth_date_confidence       DOUBLE,
    record_confidence           DOUBLE,
    n_sources                   INTEGER,
    created_at_utc              TIMESTAMP
);

CREATE TABLE IF NOT EXISTS curated.customer_xref (
    customer_id     VARCHAR NOT NULL,
    _source         VARCHAR NOT NULL,
    _source_id      VARCHAR NOT NULL,
    match_method    VARCHAR,
    match_score     DOUBLE,
    PRIMARY KEY (customer_id, _source, _source_id)
);

CREATE TABLE IF NOT EXISTS curated.match_audit (
    audit_id        VARCHAR PRIMARY KEY,
    event_type      VARCHAR,
    customer_id     VARCHAR,
    other_id        VARCHAR,
    decision        VARCHAR,
    score           DOUBLE,
    note            VARCHAR,
    created_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS curated.customer_review (
    review_id       VARCHAR PRIMARY KEY,
    left_customer   VARCHAR,
    right_customer  VARCHAR,
    score           DOUBLE,
    features        VARCHAR,
    created_at      TIMESTAMP
);
"""


ALL_DDL: str = RAW_DDL + CONFORMED_DDL + CURATED_DDL
