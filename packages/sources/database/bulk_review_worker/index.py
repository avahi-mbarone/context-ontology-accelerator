# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bulk Review Worker Lambda entry point.

Thin shim that delegates to ``coa_sources.database.bulk_review.worker.handler``
where the real logic lives. Keeps the deployable Lambda asset slim and lets us
test the handler directly without invoking the Lambda runtime.
"""

from __future__ import annotations

from coa_sources.database.bulk_review.worker import handler as _impl


def handler(event: dict, context: object) -> None:
    """SQS event handler — see ``worker.handler`` for behavior."""
    return _impl(event, context)
