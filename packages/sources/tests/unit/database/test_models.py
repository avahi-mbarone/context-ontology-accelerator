# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for domain models."""

from coa_common.domain_models import (
    BusinessMetadata,
    Column,
    DiscoveredMetadata,
    EnrichmentSource,
    ForeignKey,
    PrimaryKey,
    ReviewStatus,
    Table,
    TechnicalMetadata,
    to_dict,
)


class TestTable:
    def test_table_id_property(self):
        t = Table(name="orders", database="sales_db")
        assert t.table_id == "sales_db.orders"

    def test_defaults(self):
        t = Table(name="t", database="db")
        assert t.columns == []
        assert t.foreign_keys == []
        assert t.primary_key.columns == []
        assert t.business_metadata.description == ""
        assert t.technical_metadata.column_count == 0


class TestDiscoveredMetadata:
    def test_total_columns(self):
        metadata = DiscoveredMetadata(
            tables=[
                Table(
                    name="t1",
                    database="db",
                    columns=[
                        Column(name="a", data_type="int"),
                        Column(name="b", data_type="string"),
                    ],
                ),
                Table(
                    name="t2",
                    database="db",
                    columns=[Column(name="c", data_type="date")],
                ),
            ]
        )
        assert metadata.total_columns == 3


class TestToDict:
    def test_serializes_full_table(self):
        table = Table(
            name="orders",
            database="sales",
            data_source_id="DS#1",
            namespace_id="ns-1",
            technical_metadata=TechnicalMetadata(
                column_count=2,
                partition_keys=["order_date"],
                format="parquet",
                location="s3://bucket/orders/",
            ),
            business_metadata=BusinessMetadata(
                description="Customer orders",
                synonyms=["purchases"],
                glossary_terms=["Order Management"],
                tags=["financial"],
                enrichment_source=EnrichmentSource.AI_GENERATED,
                review_status=ReviewStatus.APPROVED.value,
            ),
            primary_key=PrimaryKey(
                columns=["order_id"],
                source=EnrichmentSource.DETERMINISTIC.value,
                confidence=1.0,
            ),
            foreign_keys=[
                ForeignKey(
                    column="customer_id",
                    target_table="customers",
                    target_column="id",
                    source=EnrichmentSource.AI_INFERRED.value,
                    confidence=0.92,
                )
            ],
            columns=[
                Column(
                    name="order_id",
                    data_type="bigint",
                    nullable=False,
                    business_metadata=BusinessMetadata(
                        description="Unique order ID",
                        tags=["identifier"],
                    ),
                ),
            ],
        )

        d = to_dict(table)

        assert d["name"] == "orders"
        assert d["technical_metadata"]["partition_keys"] == ["order_date"]
        assert d["business_metadata"]["description"] == "Customer orders"
        assert d["business_metadata"]["enrichment_source"] == "AI_GENERATED"
        assert d["primary_key"]["columns"] == ["order_id"]
        assert d["foreign_keys"][0]["target_table"] == "customers"
        assert d["columns"][0]["business_metadata"]["description"] == "Unique order ID"
