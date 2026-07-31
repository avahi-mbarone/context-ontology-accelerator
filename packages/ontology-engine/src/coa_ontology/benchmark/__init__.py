# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Benchmark utilities: golden-ontology comparison, alignment scoring."""

from coa_ontology.benchmark.golden_compare import (
    BenchmarkScore,
    ClassMatch,
    PropertyMatch,
    compare_to_golden,
)

__all__ = ["BenchmarkScore", "ClassMatch", "PropertyMatch", "compare_to_golden"]
