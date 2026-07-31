# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Induction strategy registry."""

from coa_ontology.inducer.strategies.base import InductionStrategy
from coa_ontology.inducer.strategies.rigor_ontology import RigorOntologyStrategy
from coa_ontology.inducer.strategies.table_to_ontology import TableToOntologyStrategy

STRATEGIES: dict[str, type[InductionStrategy]] = {
    "table_to_ontology": TableToOntologyStrategy,
    "rigor_ontology": RigorOntologyStrategy,
}


def get_strategy(name: str) -> type[InductionStrategy]:
    """Look up an induction strategy class by its registry name.

    Args:
        name: Registered strategy name.

    Returns:
        The strategy class registered under ``name``.

    Raises:
        ValueError: If no strategy is registered under ``name``.
    """
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGIES.keys())}")
    return STRATEGIES[name]
