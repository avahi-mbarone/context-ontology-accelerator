# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Data Access Object pattern — ABC and DynamoDB implementation."""

from coa_common.dao.base import DatastoreDAO, PaginatedResult, QueryParams
from coa_common.dao.dynamodb import DynamoDBDAO

__all__ = [
    "DatastoreDAO",
    "DynamoDBDAO",
    "PaginatedResult",
    "QueryParams",
]
