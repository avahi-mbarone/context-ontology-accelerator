# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Stratified Sampler.

Tests cover:
- √N formula computation
- k_min enforcement
- Floor threshold skipping with warning log
- Sampling all entities when N < k
- Stable ordering preservation
- CamelCase to space-separated conversion

Requirements: 3.1–3.7
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

from coa_ontology.inducer.unstructured.services.sampler import (
    _camel_to_spaced,
    sample,
)
from coa_ontology.inducer.unstructured.stores.protocol import (
    ClassRecord,
    EntityRecord,
)


def _mock_store(entities_by_class: dict[str, list[EntityRecord]]) -> MagicMock:
    """Create a mock store that returns entities by class value."""
    store = MagicMock()

    def _get_entities(classification: str, limit: int = 100):
        all_entities = entities_by_class.get(classification, [])
        return all_entities[:limit]

    store.get_entities_by_class.side_effect = _get_entities
    return store


def _make_entities(cls: str, count: int) -> list[EntityRecord]:
    """Create a list of EntityRecord instances for testing."""
    return [EntityRecord(entity_id=f"e-{cls}-{i}", value=f"entity-{i}", classification=cls) for i in range(count)]


class TestCamelToSpaced:
    """Test the CamelCase to space-separated conversion."""

    def test_single_word(self):
        assert _camel_to_spaced("Company") == "Company"

    def test_two_words(self):
        assert _camel_to_spaced("FinancialInstrument") == "Financial Instrument"

    def test_creative_work(self):
        assert _camel_to_spaced("CreativeWork") == "Creative Work"

    def test_business_segment(self):
        assert _camel_to_spaced("BusinessSegment") == "Business Segment"

    def test_operating_segment(self):
        assert _camel_to_spaced("OperatingSegment") == "Operating Segment"

    def test_empty_string(self):
        assert _camel_to_spaced("") == ""

    def test_already_spaced(self):
        # If somehow already spaced, don't double-space
        assert _camel_to_spaced("Financial Instrument") == "Financial Instrument"

    def test_all_lowercase(self):
        assert _camel_to_spaced("company") == "company"


class TestSampleSizeComputation:
    """Test that sample sizes follow k = max(k_min, ceil(sqrt(N)))."""

    def test_sqrt_formula(self):
        """For N=100, sqrt=10, k_min=5 → k=10."""
        entities = _make_entities("Company", 100)
        store = _mock_store({"Company": entities})
        distribution = [ClassRecord(value="Company", count=100)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        assert len(result["Company"]) == 10  # ceil(sqrt(100)) = 10

    def test_sqrt_formula_non_perfect_square(self):
        """For N=50, sqrt≈7.07, ceil=8, k_min=5 → k=8."""
        entities = _make_entities("Person", 50)
        store = _mock_store({"Person": entities})
        distribution = [ClassRecord(value="Person", count=50)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        assert len(result["Person"]) == math.ceil(math.sqrt(50))  # 8

    def test_k_min_enforcement(self):
        """For N=4, sqrt=2, k_min=5 → k=5, but N=4 < k=5 → sample all 4."""
        entities = _make_entities("Role", 4)
        store = _mock_store({"Role": entities})
        distribution = [ClassRecord(value="Role", count=4)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        # N=4 < k=5, so we sample all 4
        assert len(result["Role"]) == 4

    def test_k_min_larger_than_sqrt(self):
        """For N=9, sqrt=3, k_min=5 → k=5."""
        entities = _make_entities("Event", 9)
        store = _mock_store({"Event": entities})
        distribution = [ClassRecord(value="Event", count=9)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        assert len(result["Event"]) == 5


class TestFloorThreshold:
    """Test that classes below floor are skipped."""

    def test_skips_below_floor(self, caplog):
        """Classes with count < floor should be skipped with a warning."""
        store = _mock_store({})
        distribution = [
            ClassRecord(value="Strategy", count=1),
            ClassRecord(value="Company", count=100),
        ]
        entities = _make_entities("Company", 100)
        store.get_entities_by_class.side_effect = lambda classification, limit=100: (
            entities[:limit] if classification == "Company" else []
        )

        with caplog.at_level("WARNING"):
            result = sample(distribution, store, k_min=5, floor=3, seed=42)

        assert "Strategy" not in [_camel_to_spaced(k) for k in result]
        assert "Company" in result
        assert "Strategy" in caplog.text
        assert "below floor threshold" in caplog.text

    def test_floor_default_is_3(self):
        """Default floor=3 should skip classes with count < 3."""
        store = _mock_store({})
        distribution = [ClassRecord(value="Market", count=2)]

        result = sample(distribution, store, k_min=5, seed=42)

        assert result == {}

    def test_floor_exactly_at_threshold(self):
        """Class with count == floor should NOT be skipped."""
        entities = _make_entities("Tech", 3)
        store = _mock_store({"Tech": entities})
        distribution = [ClassRecord(value="Tech", count=3)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        # N=3 >= floor=3, so it's included. k=max(5, ceil(sqrt(3)))=5, but N=3 < k → sample all
        assert "Tech" in result
        assert len(result["Tech"]) == 3


class TestSamplingBehavior:
    """Test sampling mechanics."""

    def test_samples_all_when_n_less_than_k(self):
        """When N < k, all entities should be sampled."""
        entities = _make_entities("Location", 4)
        store = _mock_store({"Location": entities})
        distribution = [ClassRecord(value="Location", count=4)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        assert len(result["Location"]) == 4
        assert set(result["Location"]) == {e.entity_id for e in entities}

    def test_stable_ordering_preserved(self):
        """Sampled IDs should maintain their relative order from the store."""
        entities = _make_entities("Company", 100)
        store = _mock_store({"Company": entities})
        distribution = [ClassRecord(value="Company", count=100)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        # Check that sampled IDs are in the same relative order as the original
        all_ids = [e.entity_id for e in entities]
        sampled = result["Company"]
        indices = [all_ids.index(sid) for sid in sampled]
        assert indices == sorted(indices)

    def test_deterministic_with_seed(self):
        """Same seed should produce same sample."""
        entities = _make_entities("Company", 100)
        store = _mock_store({"Company": entities})
        distribution = [ClassRecord(value="Company", count=100)]

        result1 = sample(distribution, store, k_min=5, floor=3, seed=123)
        result2 = sample(distribution, store, k_min=5, floor=3, seed=123)

        assert result1 == result2

    def test_different_seeds_produce_different_samples(self):
        """Different seeds should (very likely) produce different samples."""
        entities = _make_entities("Company", 100)
        store = _mock_store({"Company": entities})
        distribution = [ClassRecord(value="Company", count=100)]

        result1 = sample(distribution, store, k_min=5, floor=3, seed=1)
        result2 = sample(distribution, store, k_min=5, floor=3, seed=2)

        # With 100 entities and k=10, different seeds should give different results
        assert result1["Company"] != result2["Company"]


class TestCamelCaseMapping:
    """Test that CamelCase SYS_Class values are mapped to entity class format."""

    def test_maps_camel_to_spaced_for_query(self):
        """Should query store with space-separated class value."""
        entities = _make_entities("Financial Instrument", 10)
        store = _mock_store({"Financial Instrument": entities})
        distribution = [ClassRecord(value="FinancialInstrument", count=10)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        # Result key should be the space-separated form
        assert "Financial Instrument" in result
        # Store should have been called with space-separated form
        store.get_entities_by_class.assert_called_once()
        call_args = store.get_entities_by_class.call_args
        assert call_args[1]["classification"] == "Financial Instrument" or call_args[0][0] == "Financial Instrument"

    def test_single_word_class_unchanged(self):
        """Single-word classes like 'Company' should pass through unchanged."""
        entities = _make_entities("Company", 10)
        store = _mock_store({"Company": entities})
        distribution = [ClassRecord(value="Company", count=10)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        assert "Company" in result


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_distribution(self):
        """Empty class distribution should return empty result."""
        store = _mock_store({})
        result = sample([], store, k_min=5, floor=3)
        assert result == {}

    def test_store_returns_fewer_than_count(self, caplog):
        """If store returns fewer entities than SYS_Class count, use what's available."""
        # SYS_Class says 100, but store only returns 5
        entities = _make_entities("Company", 5)
        store = _mock_store({"Company": entities})
        distribution = [ClassRecord(value="Company", count=100)]

        result = sample(distribution, store, k_min=5, floor=3, seed=42)

        # Should sample all 5 available (since 5 < k=10)
        assert len(result["Company"]) == 5

    def test_store_returns_empty(self, caplog):
        """If store returns no entities, skip with warning."""
        store = _mock_store({"Company": []})
        distribution = [ClassRecord(value="Company", count=100)]

        with caplog.at_level("WARNING"):
            result = sample(distribution, store, k_min=5, floor=3, seed=42)

        assert "Company" not in result
        assert "zero entities" in caplog.text
