# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Graph store abstractions for the unstructured induction pipeline.

This module exposes the LexicalGraphStore Protocol and its associated
record types used to interact with lexical knowledge graphs produced by
the graphrag-toolkit.
"""

from coa_ontology.inducer.unstructured.stores.na_lexical import (
    NeptuneAnalyticsLexicalStore,
)
from coa_ontology.inducer.unstructured.stores.protocol import (
    ClassRecord,
    ClassSchemaResult,
    EntityRecord,
    FactRecord,
    LexicalGraphStore,
    RelationRecord,
    TopicRecord,
)

__all__ = [
    "ClassRecord",
    "ClassSchemaResult",
    "EntityRecord",
    "FactRecord",
    "LexicalGraphStore",
    "NeptuneAnalyticsLexicalStore",
    "RelationRecord",
    "TopicRecord",
]
