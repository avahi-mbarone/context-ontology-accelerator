# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Transient-error retry for AOSS operations.

OpenSearch Serverless surfaces transient OCU-pressure / node faults as 429
(throttle / circuit_breaking_exception) and 5xx. opensearch-py's transport only
retries a subset and not consistently, so a single blip fails a whole operation
(an accept's embedding write, a delete's teardown drain, a retrieval). We wrap
every op in capped exponential backoff over :data:`OSS_RETRY_STATUS`, and bulk
writes re-submit only the transiently-failed per-item docs.

Env-tunable: ``OSS_MAX_RETRIES`` (default 6), ``OSS_MAX_BACKOFF_S`` (default 30).
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable

from opensearchpy import OpenSearch
from opensearchpy.exceptions import ConnectionError as OSConnectionError
from opensearchpy.exceptions import ConnectionTimeout, TransportError
from opensearchpy.helpers import bulk
from opensearchpy.helpers.errors import BulkIndexError

log = logging.getLogger(__name__)

# 429 (throttle / circuit-breaker) + retryable 5xx. 4xx (400/403/404/409) are
# terminal and propagate immediately.
OSS_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
OSS_MAX_RETRIES = int(os.getenv("OSS_MAX_RETRIES", "6"))
OSS_MAX_BACKOFF_S = float(os.getenv("OSS_MAX_BACKOFF_S", "30"))


def is_transient(exc: Exception) -> bool:
    """Whether an opensearch-py error is a transient AOSS fault worth retrying."""
    if isinstance(exc, (OSConnectionError, ConnectionTimeout)):
        return True  # network blip / timeout — retry
    if isinstance(exc, TransportError):
        return getattr(exc, "status_code", None) in OSS_RETRY_STATUS
    return False


def _backoff(attempt: int, max_backoff_s: float = OSS_MAX_BACKOFF_S) -> float:
    """Capped exponential backoff with jitter: min(max_backoff_s, 2**attempt) + [0,1)."""
    return min(max_backoff_s, 2.0**attempt) + random.uniform(0, 1)


def _status(exc: Exception) -> object:
    """Best-effort status/label for the retry log line.

    httpx puts it on exc.response.status_code; opensearch-py on
    exc.status_code; else the type name.
    """
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if code is not None else type(exc).__name__


def retry_call[T](
    op: str,
    fn: Callable[[], T],
    *,
    is_transient: Callable[[Exception], bool],
    max_retries: int,
    max_backoff_s: float,
) -> T:
    """Generic capped-exponential-backoff retry loop.

    Retries `fn` while `is_transient(exc)` and attempts remain; re-raises on
    exhaustion or a non-transient error. `oss_retry` and the httpx catalog
    client both build on this — inject the predicate + limits, share the loop.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — re-raised below unless transient
            if not is_transient(exc) or attempt >= max_retries:
                raise
            backoff = _backoff(attempt, max_backoff_s)
            log.warning(
                "retry %s transient error (%s); attempt %d/%d in %.1fs",
                op,
                _status(exc),
                attempt + 1,
                max_retries,
                backoff,
            )
            time.sleep(backoff)
            attempt += 1


def oss_retry[T](op: str, fn: Callable[[], T]) -> T:
    """Run an AOSS operation with capped exponential backoff on transient faults.

    Retries 429/5xx (TransportError) and connection errors/timeouts up to
    :data:`OSS_MAX_RETRIES`; on exhaustion re-raises the real error. Non-transient
    errors (400/404/409, RequestError, auth) propagate immediately.
    """
    return retry_call(
        op,
        fn,
        is_transient=is_transient,
        max_retries=OSS_MAX_RETRIES,
        max_backoff_s=OSS_MAX_BACKOFF_S,
    )


def bulk_with_retry(client: OpenSearch, actions: list[dict]) -> None:
    """Bulk-index ``actions``, retrying items that fail with a transient status.

    ``helpers.bulk``'s own ``max_retries`` only re-sends items that return 429;
    a per-item 5xx (AOSS "Internal error occurred while processing request")
    raises ``BulkIndexError`` immediately with no retry. Whole-request wrapping
    (:func:`oss_retry`) can't help either — the HTTP request itself returned 200,
    the failure is per-document. So on ``BulkIndexError`` we inspect each item's
    status and re-submit ONLY the transiently-failed actions (retrying the whole
    batch would duplicate the succeeded docs, since AOSS auto-assigns ``_id``).
    """
    if not actions:
        return
    pending = actions
    attempt = 0
    while True:
        try:
            bulk(client, pending, chunk_size=10, max_retries=3, initial_backoff=2, max_backoff=30)
            return
        except BulkIndexError as exc:
            # exc.errors is a list of per-item result dicts, e.g.
            # [{"index": {"status": 500, "error": {...}, "data": {...}}}].
            retryable_data: list[dict] = []
            for item in exc.errors:
                (op_result,) = item.values()  # single-key dict keyed by op type
                status = op_result.get("status")
                data = op_result.get("data")
                if status in OSS_RETRY_STATUS and data is not None:
                    retryable_data.append(data)
            # Nothing transient, or retries exhausted → surface the real error.
            if not retryable_data or attempt >= OSS_MAX_RETRIES:
                raise
            backoff = _backoff(attempt)
            log.warning(
                "OSS bulk: %d/%d docs failed transiently; retry %d/%d in %.1fs",
                len(retryable_data),
                len(pending),
                attempt + 1,
                OSS_MAX_RETRIES,
                backoff,
            )
            time.sleep(backoff)
            # Re-submit only the failed docs. ``data`` is the source document; it
            # carries neither _index nor _op_type, so rebuild the action envelope
            # from the original actions (all share the same index within a batch).
            index = pending[0]["_index"]
            pending = [{"_op_type": "index", "_index": index, **d} for d in retryable_data]
            attempt += 1
