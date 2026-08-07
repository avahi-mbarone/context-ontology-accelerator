# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Structured logging setup using structlog."""

import logging

import structlog
from structlog.typing import Processor

# Shared processor chain. Applied to structlog-native events and, via
# ``ProcessorFormatter``, to records coming from the stdlib ``logging`` module,
# so both render as the same JSON shape. Annotated explicitly: the entries have
# differing callable signatures, so an unannotated list infers as
# ``list[object]`` and fails to type-check where it is unpacked below.
_SHARED_PROCESSORS: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.StackInfoRenderer(),
    structlog.dev.set_exc_info,
    structlog.processors.format_exc_info,
    structlog.processors.TimeStamper(fmt="iso"),
]


def setup_logging(log_level: str = "INFO", stdlib_log_level: str | None = None) -> None:
    """Configure structlog, and bridge the stdlib ``logging`` module into it.

    Third-party libraries (graphrag-toolkit, botocore, opensearch-py) log via
    stdlib ``logging.getLogger(__name__)``, not structlog. Configuring structlog
    alone leaves the stdlib root logger with no handler, so those records fall
    through to ``logging.lastResort`` — a hardcoded stderr handler pinned at
    WARNING that ignores logger levels. The effect is that every third-party
    INFO/DEBUG record is silently discarded, and the WARNINGs that do escape are
    unstructured (no timestamp, no logger name, and an inconsistent prefix
    depending on whether something already triggered ``basicConfig``).

    Installing a root handler backed by ``ProcessorFormatter`` routes stdlib
    records through the same processor chain, so third-party logs land in
    CloudWatch as queryable JSON alongside our own.

    Args:
        log_level: Level for structlog-native loggers (our own code).
        stdlib_log_level: Level for the stdlib root logger (third-party
            libraries). Defaults to WARNING, which matches the volume
            ``lastResort`` already let through — so existing callers keep the
            same log volume and only gain structure. Lower it per-service (e.g.
            INFO) where third-party progress logs are worth the extra lines;
            botocore/boto3 at INFO is chatty on request-heavy workloads.
    """
    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ``foreign_pre_chain`` runs on records originating from stdlib logging;
    # ``processors`` renders the final line. ``remove_processors_meta`` strips
    # the internal bookkeeping keys ProcessorFormatter adds. ``add_logger_name``
    # emits the originating module as ``logger``, so third-party output can be
    # filtered by package in CloudWatch Logs Insights.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.stdlib.add_logger_name, *_SHARED_PROCESSORS],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Replace any pre-existing handlers so a module that already called
    # ``basicConfig`` doesn't double-emit every record.
    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    resolved = stdlib_log_level if stdlib_log_level is not None else "WARNING"
    root.setLevel(getattr(logging, resolved.upper(), logging.WARNING))
