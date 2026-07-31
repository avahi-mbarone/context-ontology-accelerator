# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models mirroring a simplified OpenMetadata entity schema."""

from pydantic import BaseModel


class EntityReference(BaseModel):
    id: str
    type: str
    name: str
    fullyQualifiedName: str
    serviceType: str | None = None


class TagLabel(BaseModel):
    tagFQN: str
    source: str = "Classification"


class OwnerReference(BaseModel):
    id: str
    type: str
    name: str


# --- Database ---


class Database(BaseModel):
    id: str
    name: str
    displayName: str | None = None
    fullyQualifiedName: str
    description: str | None = None
    service: EntityReference | None = None
    tags: list[TagLabel] = []
    owners: list[OwnerReference] = []


# --- DatabaseSchema ---


class DatabaseSchema(BaseModel):
    id: str
    name: str
    displayName: str | None = None
    fullyQualifiedName: str
    description: str | None = None
    database: EntityReference | None = None


# --- Table ---


class TableConstraint(BaseModel):
    constraintType: str  # UNIQUE | PRIMARY_KEY | FOREIGN_KEY | SORT_KEY | DIST_KEY | CLUSTER_KEY
    columns: list[str]
    referredColumns: list[str] | None = None
    relationshipType: str | None = None  # ONE_TO_ONE | ONE_TO_MANY | MANY_TO_ONE | MANY_TO_MANY


class Column(BaseModel):
    name: str
    dataType: str
    dataLength: int | None = None
    precision: int | None = None
    scale: int | None = None
    description: str | None = None
    constraint: str | None = None  # NULL | NOT_NULL | UNIQUE | PRIMARY_KEY
    ordinalPosition: int | None = None
    tags: list[TagLabel] = []


class Table(BaseModel):
    id: str
    name: str
    displayName: str | None = None
    fullyQualifiedName: str
    description: str | None = None
    tableType: str | None = "Regular"
    databaseSchema: EntityReference | None = None
    columns: list[Column] = []
    tableConstraints: list[TableConstraint] | None = None
    tags: list[TagLabel] = []
