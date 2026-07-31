# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for PK-sharing subtype detection and chain walking."""

from __future__ import annotations

import pytest
from coa_ontology.inducer.services.data_catalog import CatalogConstraint, CatalogTable
from coa_ontology.inducer.services.subtype_detection import (
    _single_col_fks,
    _single_pk_column,
    build_subtype_chains,
    detect_pk_sharing_subtypes,
)

pytestmark = pytest.mark.unit


def _table(
    name: str,
    pk: str | None = None,
    fks: list[tuple[str, str]] | None = None,
    composite_pk: list[str] | None = None,
) -> CatalogTable:
    """Build a CatalogTable with a single-col PK and FKs.

    fks: list of (child_col, "PARENT.COL") pairs.
    """
    constraints: list[CatalogConstraint] = []
    if pk is not None:
        constraints.append(CatalogConstraint(constraintType="PRIMARY_KEY", columns=[pk]))
    if composite_pk is not None:
        constraints.append(CatalogConstraint(constraintType="PRIMARY_KEY", columns=composite_pk))
    for child_col, referred in fks or []:
        constraints.append(
            CatalogConstraint(constraintType="FOREIGN_KEY", columns=[child_col], referredColumns=[referred])
        )
    return CatalogTable(
        id=name,
        name=name,
        fullyQualifiedName=f"db.{name}",
        tableConstraints=constraints or None,
    )


# ── _single_pk_column ────────────────────────────────────────────────


def test_single_pk_column_returns_single_col() -> None:
    assert _single_pk_column(_table("t", pk="ID")) == "ID"


def test_single_pk_column_none_without_constraints() -> None:
    assert _single_pk_column(_table("t")) is None


def test_single_pk_column_none_for_composite() -> None:
    assert _single_pk_column(_table("t", composite_pk=["A", "B"])) is None


# ── _single_col_fks ──────────────────────────────────────────────────


def test_single_col_fks_parses_parent_table_and_col() -> None:
    t = _table("child", pk="ID", fks=[("ID", "db.Parent.PID")])
    assert _single_col_fks(t) == [("ID", "Parent", "PID")]


def test_single_col_fks_skips_malformed_referred_column() -> None:
    t = _table("child", pk="ID", fks=[("ID", "PID")])  # no dot → cannot parse parent
    assert _single_col_fks(t) == []


def test_single_col_fks_empty_without_constraints() -> None:
    assert _single_col_fks(_table("t")) == []


# ── detect_pk_sharing_subtypes ───────────────────────────────────────


def test_detect_confirmed_when_two_children_share_parent_pk() -> None:
    parent = _table("Claim", pk="CLAIM_ID")
    child_a = _table("LossPayment", pk="CLAIM_ID", fks=[("CLAIM_ID", "db.Claim.CLAIM_ID")])
    child_b = _table("Reserve", pk="CLAIM_ID", fks=[("CLAIM_ID", "db.Claim.CLAIM_ID")])
    confirmed, suggested = detect_pk_sharing_subtypes([parent, child_a, child_b])
    assert ("LossPayment", "Claim") in confirmed
    assert ("Reserve", "Claim") in confirmed
    assert suggested == set()


def test_detect_suggested_when_single_child() -> None:
    parent = _table("Customer", pk="CUST_ID")
    child = _table("CustomerAddress", pk="CUST_ID", fks=[("CUST_ID", "db.Customer.CUST_ID")])
    confirmed, suggested = detect_pk_sharing_subtypes([parent, child])
    assert confirmed == set()
    assert ("CustomerAddress", "Customer") in suggested


def test_detect_ignores_when_fk_col_differs_from_pk() -> None:
    parent = _table("Parent", pk="PID")
    # child's FK is on a different column than its PK → not a PK-sharing subtype
    child = _table("Child", pk="CID", fks=[("OTHER", "db.Parent.PID")])
    confirmed, suggested = detect_pk_sharing_subtypes([parent, child])
    assert confirmed == set()
    assert suggested == set()


def test_detect_ignores_self_fk() -> None:
    # A table whose PK is also an FK pointing at itself is malformed → skipped.
    t = _table("Node", pk="ID", fks=[("ID", "db.Node.ID")])
    confirmed, suggested = detect_pk_sharing_subtypes([t])
    assert confirmed == set()
    assert suggested == set()


def test_detect_ignores_pk_fk_column_mismatch() -> None:
    # Parent PK column differs from the column the child FK points at → skipped.
    parent = _table("Parent", pk="PID")
    child = _table("Child", pk="CID", fks=[("CID", "db.Parent.OTHER_COL")])
    confirmed, suggested = detect_pk_sharing_subtypes([parent, child])
    assert confirmed == set()
    assert suggested == set()


# ── build_subtype_chains ─────────────────────────────────────────────


def test_build_chains_transitive() -> None:
    pairs = {("C", "B"), ("B", "A")}
    chains = build_subtype_chains(pairs)
    assert chains["C"] == ["B", "A"]
    assert chains["B"] == ["A"]


def test_build_chains_breaks_on_cycle() -> None:
    # A→B→A is a cycle; the walk stops at the first repeat.
    pairs = {("A", "B"), ("B", "A")}
    chains = build_subtype_chains(pairs)
    # Each child's chain terminates before revisiting itself.
    assert chains["A"] == ["B"]
    assert chains["B"] == ["A"]


def test_build_chains_respects_max_depth() -> None:
    pairs = {("E", "D"), ("D", "C"), ("C", "B"), ("B", "A")}
    chains = build_subtype_chains(pairs, max_depth=2)
    # Walk from E is truncated at max_depth=2 ancestors.
    assert chains["E"] == ["D", "C"]


def test_build_chains_empty_input() -> None:
    assert build_subtype_chains(set()) == {}
