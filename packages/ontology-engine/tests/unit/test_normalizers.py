# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for predicate normalization and XSD type inference.

Requirements: 19.1–19.4, 18.1–18.8
"""

import pytest

pytestmark = pytest.mark.unit

from coa_ontology.inducer.unstructured.services.normalizers import (
    infer_xsd_type,
    normalize_predicate,
    select_canonical_label,
)


class TestNormalizePredicate:
    """Test predicate normalization."""

    def test_uppercase_to_lowercase(self):
        assert normalize_predicate("OPERATES_IN") == "operates_in"

    def test_mixed_case(self):
        assert normalize_predicate("Works_For") == "works_for"

    def test_spaces_to_underscores(self):
        assert normalize_predicate("works for") == "works_for"

    def test_all_caps_with_underscores(self):
        assert normalize_predicate("PART_OF") == "part_of"

    def test_strips_special_chars(self):
        assert normalize_predicate("has-age!") == "hasage"

    def test_collapses_consecutive_underscores(self):
        assert normalize_predicate("a__b___c") == "a_b_c"

    def test_strips_leading_trailing_underscores(self):
        assert normalize_predicate("_hello_") == "hello"
        assert normalize_predicate("___test___") == "test"

    def test_spaces_and_special_combined(self):
        assert normalize_predicate("HAS POLICY (v2)") == "has_policy_v2"

    def test_idempotent(self):
        """normalize_predicate(normalize_predicate(s)) == normalize_predicate(s)"""
        cases = [
            "OPERATES_IN",
            "works for",
            "HAS_POLICY",
            "PART OF",
            "a - b",
            "ABBREVIATION_OF",
        ]
        for s in cases:
            once = normalize_predicate(s)
            twice = normalize_predicate(once)
            assert once == twice, f"Not idempotent for {s!r}: {once!r} != {twice!r}"

    def test_empty_string(self):
        assert normalize_predicate("") == ""

    def test_only_special_chars(self):
        assert normalize_predicate("@#$%") == ""

    def test_numbers_preserved(self):
        assert normalize_predicate("version_2") == "version_2"

    def test_real_graph_predicates(self):
        """Test with actual predicates from the dev graph."""
        assert normalize_predicate("ABBREVIATION_OF") == "abbreviation_of"
        assert normalize_predicate("ACCESSED_VIA") == "accessed_via"
        assert normalize_predicate("ACCOUNTED_AS") == "accounted_as"
        assert normalize_predicate("CEASED OPERATIONS IN") == "ceased_operations_in"


class TestInferXsdType:
    """Test XSD type inference."""

    def test_all_integers(self):
        assert infer_xsd_type(["42", "7", "100", "-5"]) == "xsd:integer"

    def test_all_decimals(self):
        assert infer_xsd_type(["3.14", "2.71", "0.5"]) == "xsd:decimal"

    def test_all_booleans(self):
        assert infer_xsd_type(["true", "false", "True", "FALSE"]) == "xsd:boolean"

    def test_all_dates(self):
        assert infer_xsd_type(["2023-04-30", "2024-01-15"]) == "xsd:date"

    def test_all_datetimes(self):
        assert infer_xsd_type(["2023-04-30T10:00:00Z", "2024-01-15T08:30:00+05:00"]) == "xsd:dateTime"

    def test_datetime_without_seconds(self):
        assert infer_xsd_type(["2023-04-30T10:00Z"]) == "xsd:dateTime"

    def test_mixed_types_returns_string(self):
        assert infer_xsd_type(["42", "hello", "true"]) == "xsd:string"

    def test_mixed_integer_and_decimal(self):
        assert infer_xsd_type(["42", "3.14"]) == "xsd:string"

    def test_empty_list(self):
        assert infer_xsd_type([]) == "xsd:string"

    def test_all_empty_strings(self):
        assert infer_xsd_type(["", "  ", ""]) == "xsd:string"

    def test_natural_language_is_string(self):
        """Real fact values from the dev graph should be xsd:string."""
        assert (
            infer_xsd_type(
                [
                    "7.27 billion",
                    "April 30, 2023",
                    "44%",
                    "$6,291 thousand",
                ]
            )
            == "xsd:string"
        )

    def test_single_value(self):
        assert infer_xsd_type(["42"]) == "xsd:integer"

    def test_positive_sign_integer(self):
        assert infer_xsd_type(["+42"]) == "xsd:integer"

    def test_whitespace_stripped(self):
        assert infer_xsd_type(["  42  ", " 7 "]) == "xsd:integer"


class TestSelectCanonicalLabel:
    """Test canonical label selection."""

    def test_picks_highest_count(self):
        assert select_canonical_label({"OPERATES_IN": 5, "operates_in": 2}) == "OPERATES_IN"

    def test_breaks_ties_lexicographically(self):
        # Same count → pick lexicographically smallest
        assert select_canonical_label({"beta": 3, "alpha": 3}) == "alpha"

    def test_single_entry(self):
        assert select_canonical_label({"PART_OF": 10}) == "PART_OF"

    def test_raises_on_empty(self):
        with pytest.raises(ValueError, match="empty"):
            select_canonical_label({})

    def test_many_variants(self):
        originals = {
            "OPERATES IN": 1,
            "OPERATES_IN": 10,
            "operates_in": 5,
            "Operates In": 2,
        }
        assert select_canonical_label(originals) == "OPERATES_IN"
