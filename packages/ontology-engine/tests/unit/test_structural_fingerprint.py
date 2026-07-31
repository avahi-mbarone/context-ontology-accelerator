# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Structural-fingerprint canonicalization (duplicate-induction detection).

The fingerprint must be stable across scans of the SAME logical schema even
when the connector reports types/constraints differently — otherwise a re-scan
of an already-inducted source fails to dedupe and runs a fresh induction.
Regression for the observed case: a JDBC scan reporting ``character varying`` /
``constraint=None`` produced a different fingerprint than an earlier scan of
the same insurance schema.
"""

from __future__ import annotations

import pytest
from coa_ontology.induce_catalog import _compute_structural_fingerprint
from coa_ontology.inducer.services.data_catalog import (
    CatalogColumn,
    CatalogConstraint,
    CatalogTable,
)

pytestmark = pytest.mark.unit


def _tbl(name, cols, cons=None):
    return CatalogTable(id=f"t-{name}", name=name, fullyQualifiedName=f"db.{name}", columns=cols, tableConstraints=cons)


class TestFingerprintCanonicalization:
    def test_equivalent_type_spellings_hash_identically(self):
        """``character varying`` (PG) and ``VARCHAR`` (Glue) → same fingerprint."""
        pg = _tbl(
            "policy",
            [CatalogColumn(name="id", dataType="integer"), CatalogColumn(name="num", dataType="character varying")],
        )
        glue = _tbl("policy", [CatalogColumn(name="id", dataType="INT"), CatalogColumn(name="num", dataType="VARCHAR")])
        assert _compute_structural_fingerprint([pg]) == _compute_structural_fingerprint([glue])

    def test_constraint_detection_difference_does_not_change_fingerprint(self):
        """A scan that detects PK/NOT NULL vs one that reports constraint=None
        must still dedupe — constraint detection isn't part of class identity."""
        with_cons = _tbl(
            "policy",
            [CatalogColumn(name="id", dataType="INTEGER", constraint="PRIMARY_KEY")],
            [CatalogConstraint(constraintType="PRIMARY_KEY", columns=["id"])],
        )
        without_cons = _tbl("policy", [CatalogColumn(name="id", dataType="INTEGER", constraint=None)])
        assert _compute_structural_fingerprint([with_cons]) == _compute_structural_fingerprint([without_cons])

    def test_fk_fqn_vs_bare_reference_hash_identically(self):
        """FK referredColumns ``db.customers.id`` and ``customers.id`` match."""
        fqn = _tbl(
            "orders",
            [CatalogColumn(name="customer_id", dataType="INT")],
            [
                CatalogConstraint(
                    constraintType="FOREIGN_KEY", columns=["customer_id"], referredColumns=["db.customers.id"]
                )
            ],
        )
        bare = _tbl(
            "orders",
            [CatalogColumn(name="customer_id", dataType="INT")],
            [
                CatalogConstraint(
                    constraintType="FOREIGN_KEY", columns=["customer_id"], referredColumns=["customers.id"]
                )
            ],
        )
        assert _compute_structural_fingerprint([fqn]) == _compute_structural_fingerprint([bare])

    def test_genuinely_different_schema_differs(self):
        """A real structural change (extra column) MUST produce a new fingerprint."""
        base = _tbl("policy", [CatalogColumn(name="id", dataType="INT")])
        extended = _tbl(
            "policy", [CatalogColumn(name="id", dataType="INT"), CatalogColumn(name="premium", dataType="DECIMAL")]
        )
        assert _compute_structural_fingerprint([base]) != _compute_structural_fingerprint([extended])

    def test_different_type_class_differs(self):
        """Same column name, genuinely different type class → different fingerprint."""
        as_int = _tbl("t", [CatalogColumn(name="c", dataType="INTEGER")])
        as_str = _tbl("t", [CatalogColumn(name="c", dataType="VARCHAR")])
        assert _compute_structural_fingerprint([as_int]) != _compute_structural_fingerprint([as_str])

    def test_table_order_independent(self):
        """Fingerprint is order-independent across the table list."""
        a = _tbl("a", [CatalogColumn(name="id", dataType="INT")])
        b = _tbl("b", [CatalogColumn(name="id", dataType="INT")])
        assert _compute_structural_fingerprint([a, b]) == _compute_structural_fingerprint([b, a])
