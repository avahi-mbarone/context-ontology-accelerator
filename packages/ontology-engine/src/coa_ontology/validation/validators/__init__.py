# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ontology validators grouped by tier (structural, semantic, and quality checks)."""

from abc import ABC, abstractmethod

from rdflib import Graph

from coa_ontology.validation.schemas import ValidationFinding


class OntologyValidator(ABC):
    """Interface for all validators."""

    @abstractmethod
    def validate(self, graph: Graph, **kwargs) -> list[ValidationFinding]:
        """Inspect the ontology graph and return the findings raised by this validator.

        Args:
            graph: The ontology graph to validate.
            **kwargs: Validator-specific options (e.g. competency questions).

        Returns:
            A list of validation findings; empty when the graph passes this check.
        """
        ...
