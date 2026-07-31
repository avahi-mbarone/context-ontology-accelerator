# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Context loader for enriched class descriptions.

Builds :class:`EntityContext` records (entity label + per-entity fact strings)
from a :class:`~coa_ontology.inducer.unstructured.stores.protocol.LexicalGraphStore`
output. This is the bridge between the sampler / store layer and the
enriched description generator.

The loader is optional: the default label-only description path
(``generate_descriptions``) does NOT need it. The enriched path
(``generate_descriptions_with_context``) does.

Usage::

    from coa_ontology.inducer.unstructured.services.context_loader import (
        load_class_contexts,
    )

    # ``sampled`` comes from the Stratified_Sampler:
    #   {"Company": ["entity_id_1", "entity_id_2", ...], "Person": [...]}
    # ``label_by_id`` maps each entity_id to its surface-form label.
    contexts = load_class_contexts(sampled, label_by_id, store)
    # contexts: {"Company": [EntityContext(label="...", facts=[...]), ...], ...}
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from coa_ontology.inducer.unstructured.services.description_generator import (
    MAX_FACTS_PER_ENTITY,
    EntityContext,
)

if TYPE_CHECKING:
    from coa_ontology.inducer.unstructured.stores.protocol import (
        FactRecord,
        LexicalGraphStore,
    )

log = logging.getLogger(__name__)


def _format_fact(fact: FactRecord) -> str:
    """Render one fact as a compact human-readable string for the LLM prompt.

    Format depends on whether the fact has an object entity:

    - SPO (object entity present)::

          "<subject_value> -- <predicate> --> <object_value>"

    - Predicate-only (no object entity; the predicate text encodes the
      whole statement, common in graphrag-toolkit output)::

          "<predicate>"

    The subject is omitted in the SPO case ONLY if it would be redundant
    — but most graphs include the subject inside the predicate text too,
    so we keep both. The exact phrasing is informative for the LLM, not
    structurally important.

    Args:
        fact: A ``FactRecord`` from the lexical graph store.

    Returns:
        A single-line string suitable for inclusion in an LLM prompt.
    """
    if fact.object_value is not None:
        return f"{fact.subject_value} -- {fact.predicate} --> {fact.object_value}"
    # Predicate-only — the predicate text already encodes everything.
    return fact.predicate


def load_class_contexts(
    sampled: dict[str, list[str]],
    label_by_id: dict[str, str],
    store: LexicalGraphStore,
    *,
    max_facts_per_entity: int = MAX_FACTS_PER_ENTITY,
) -> dict[str, list[EntityContext]]:
    """Fetch facts for sampled entities and assemble enriched contexts.

    For each class in ``sampled``:

    1. Look up each entity's surface-form label via ``label_by_id``. Drop
       entities with no label (logs WARNING; should not normally happen).
    2. Issue a single batched ``get_facts_for_entities`` call for all that
       class's entities (the store handles internal batching at 500 IDs).
    3. Group facts by subject entity ID.
    4. Build an :class:`EntityContext` per entity, capping facts at
       ``max_facts_per_entity`` (preserving graph-store order, which is
       typically by descending interestingness in graphrag-toolkit).

    Entities for which no facts are returned still produce an
    :class:`EntityContext` (with ``facts=[]``) — the enriched prompt then
    treats them as label-only inputs.

    Args:
        sampled: Mapping from class label to a list of entity IDs (the
            output of ``Stratified_Sampler.sample``).
        label_by_id: Mapping from entity ID to surface-form label. Keys
            must include every entity ID present in ``sampled``; missing
            keys cause those entities to be dropped with a warning.
        store: A :class:`LexicalGraphStore` instance.
        max_facts_per_entity: Per-entity cap on the number of facts
            included in the resulting :class:`EntityContext`. Defaults to
            ``description_generator.MAX_FACTS_PER_ENTITY``.

    Returns:
        Mapping from each class label to a list of :class:`EntityContext`
        records. Class labels with zero (post-filter) entities are still
        present with an empty list.
    """
    if max_facts_per_entity < 0:
        raise ValueError(f"max_facts_per_entity must be >= 0, got {max_facts_per_entity}")

    result: dict[str, list[EntityContext]] = {}

    for class_label, entity_ids in sampled.items():
        # Filter to only entities we have a label for.
        kept_ids: list[str] = []
        for eid in entity_ids:
            if eid in label_by_id:
                kept_ids.append(eid)
            else:
                log.warning(
                    "Entity ID %r in class %r not found in label_by_id; skipping",
                    eid,
                    class_label,
                )

        if not kept_ids:
            result[class_label] = []
            continue

        # Single batched call for all entities of this class. The store
        # internally chunks at 500 IDs.
        facts = store.get_facts_for_entities(kept_ids)

        # Group facts by subject entity. We match on subject_value (the
        # surface-form label) since that's what FactRecord exposes; this
        # is sufficient because each entity has a unique label within a
        # class (collisions across classes don't matter here — we only
        # process this class's entities).
        facts_by_label: dict[str, list[str]] = {}
        for f in facts:
            facts_by_label.setdefault(f.subject_value, []).append(_format_fact(f))

        contexts: list[EntityContext] = []
        for eid in kept_ids:
            label = label_by_id[eid]
            entity_facts = facts_by_label.get(label, [])
            contexts.append(
                EntityContext(
                    label=label,
                    facts=entity_facts[:max_facts_per_entity],
                )
            )

        log.debug(
            "Class %r: built %d enriched contexts, total %d facts after capping",
            class_label,
            len(contexts),
            sum(len(c.facts) for c in contexts),
        )
        result[class_label] = contexts

    return result
