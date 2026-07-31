# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pydantic schemas and enums for ontology validation requests, findings, and reports."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ValidationTier(StrEnum):
    """Validation tier: blocking (tier 1), scoring (tier 2), or review (tier 3)."""

    tier1_blocking = "tier1_blocking"
    tier2_scoring = "tier2_scoring"
    tier3_review = "tier3_review"


class Severity(StrEnum):
    """Severity of a validation finding: error (blocks), warning (scored), or info (review)."""

    error = "error"  # tier 1 — blocks
    warning = "warning"  # tier 2 — scored
    info = "info"  # tier 3 — flagged for review


class ValidationFinding(BaseModel):
    """A single validation result: its tier, severity, code, message, and subject."""

    validator: str  # which validator produced this
    tier: ValidationTier
    severity: Severity
    code: str  # machine-readable finding code
    message: str
    subject: str | None = None  # URI of the offending element
    details: dict | None = None


class ValidationRequest(BaseModel):
    """Request to validate an ontology.

    The namespace is bound from the request's ``?namespace=`` query param,
    not the body — keep it off this schema so a caller can't pass a
    different namespace than the one their token authorized.
    """

    ontology_id: str  # fetch from ontology-catalog by ID (URI)
    ontology_turtle: str | None = None  # optional: override with inline Turtle content
    tiers: list[ValidationTier] = [  # which tiers to run
        ValidationTier.tier1_blocking,
        ValidationTier.tier2_scoring,
        ValidationTier.tier3_review,
    ]
    shacl_shapes_turtle: str | None = None  # optional custom SHACL shapes
    competency_questions: list[str] | None = None  # natural-language questions the ontology should answer


class StructuralMetrics(BaseModel):
    """OntoQA-style structural metrics (Tier 2)."""

    class_count: int = 0
    object_property_count: int = 0
    datatype_property_count: int = 0
    relationship_richness: float | None = None  # non-inheritance / total relations
    attribute_richness: float | None = None  # datatype props / classes
    inheritance_richness: float | None = None  # subclass relations / classes
    max_depth: int | None = None
    connected_components: int | None = None


class ValidationReport(BaseModel):
    """Aggregated result of a validation run: pass/fail, findings, metrics, and tiers run."""

    job_id: str
    ontology_id: str | None = None
    passed: bool  # True if no tier1 errors
    findings: list[ValidationFinding]
    metrics: StructuralMetrics | None = None
    tiers_run: list[ValidationTier]
    created_at: datetime


class JobStatus(StrEnum):
    """Lifecycle state of an asynchronous validation job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobResponse(BaseModel):
    """API response wrapping a validation job's status and, when done, its report."""

    job_id: str
    status: JobStatus
    created_at: datetime
    report: ValidationReport | None = None
    error: str | None = None
