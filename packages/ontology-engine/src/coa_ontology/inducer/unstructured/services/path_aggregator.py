# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Path Aggregator for property proposals from SYS_RELATION edges.

Reads ``__SYS_RELATION__`` edges between ``__SYS_Class__`` nodes (returned
by ``LexicalGraphStore.get_class_relations()``) and derives candidate
property declarations grounded in actual graph structure — without
requiring an LLM discovery pass.

Each proposal is a tuple ``(domain_class, predicate, range_class, frequency)``
where ``predicate`` is the normalized predicate label (per
``normalize_predicate()``). Edges that share the same normalized predicate
between the same class pair are merged into a single proposal with their
frequencies summed.

Usage::

    from coa_ontology.inducer.unstructured.services.path_aggregator import (
        aggregate,
    )

    relations = store.get_class_relations()
    proposals = aggregate(relations, min_frequency=1)
    # proposals: [PropertyProposal(domain="Company", predicate="operates_in",
    #                              range="Country", frequency=42), ...]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from coa_ontology.inducer.unstructured.services.normalizers import (
    normalize_predicate,
)

if TYPE_CHECKING:
    from coa_ontology.inducer.unstructured.stores.protocol import (
        RelationRecord,
    )


@dataclass
class PropertyProposal:
    """One candidate property declaration derived from SYS_RELATION edges.

    Attributes:
        domain: The domain class label (subject side, e.g. "Company").
        predicate: The normalized predicate label (e.g. "operates_in").
        range: The range class label (object side, e.g. "Country").
        frequency: Total observation count across merged edges sharing
            the same (domain, predicate, range) triple.
    """

    domain: str
    predicate: str
    range: str
    frequency: int


def aggregate(
    relations: list[RelationRecord],
    min_frequency: int = 1,
) -> list[PropertyProposal]:
    """Aggregate SYS_RELATION edges into property proposals.

    For each ``RelationRecord``:
    - Normalize the predicate using ``normalize_predicate()``.
    - Merge edges sharing the same ``(source_class, normalized_predicate,
      target_class)`` triple by summing their counts.

    Then:
    - Exclude proposals whose summed frequency is below ``min_frequency``.
    - Sort by frequency descending; break ties lexicographically by
      ``(domain, predicate, range)``.

    Args:
        relations: List of ``RelationRecord`` from
            ``LexicalGraphStore.get_class_relations()``. May be empty.
        min_frequency: Minimum frequency threshold for inclusion
            (default 1, includes all observed edges).

    Returns:
        Sorted list of ``PropertyProposal`` instances. Empty if the input
        is empty or all proposals fall below ``min_frequency``.
    """
    if not relations:
        return []

    # Merge edges with the same (domain, normalized predicate, range)
    merged: dict[tuple[str, str, str], int] = {}
    for rel in relations:
        normalized = normalize_predicate(rel.predicate)
        # Skip relations whose predicate normalizes to the empty string —
        # they cannot produce a valid property IRI downstream.
        if not normalized:
            continue
        key = (rel.source_class, normalized, rel.target_class)
        merged[key] = merged.get(key, 0) + rel.count

    # Build proposals, applying the min_frequency filter
    proposals = [
        PropertyProposal(
            domain=domain,
            predicate=predicate,
            range=range_,
            frequency=frequency,
        )
        for (domain, predicate, range_), frequency in merged.items()
        if frequency >= min_frequency
    ]

    # Sort by frequency descending, ties broken lexicographically by
    # (domain, predicate, range).
    proposals.sort(key=lambda p: (-p.frequency, p.domain, p.predicate, p.range))

    return proposals
