# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Lexical-KG retrieval via graphrag-toolkit. No ontology consulted."""

from .baseline_retriever import BaselineLexicalRetriever, BaselineResult

__all__ = ["BaselineLexicalRetriever", "BaselineResult"]
