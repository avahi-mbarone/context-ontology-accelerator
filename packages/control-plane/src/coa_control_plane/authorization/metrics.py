# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""CloudWatch EMF metrics for the API Gateway custom Lambda authorizer.

Distinguishes two signal types on the deny path (see handler.py):

* ``AuthorizationDeny`` — Cedar actually evaluated the request and denied it
  (including the ``denyAll`` fallback for unmapped routes). This is the
  security-relevant signal: alarm on this to catch attack patterns or
  misconfigured permissions.
* ``AuthorizerError`` — the request never reached a real authorization
  decision (invalid token, missing principal, role-resolution failure,
  namespace-status lookup failure, or an exception during Cedar evaluation).
  These are availability/config signals, not authorization decisions, and are
  kept out of ``AuthorizationDeny`` so that metric stays a clean security
  signal.
"""

from __future__ import annotations

from coa_common.metrics import emit_metric

_NAMESPACE = "SemanticContext/Authorization"


def emit_authorization_deny(*, action: str, reason: str) -> None:
    """Emit a metric for a request that Cedar evaluated and denied."""
    emit_metric(_NAMESPACE, "AuthorizationDeny", 1, "Count", action=action, reason=reason)


def emit_authorizer_error(*, reason: str, action: str | None = None) -> None:
    """Emit a metric for a request denied due to an error, not a Cedar decision."""
    emit_metric(_NAMESPACE, "AuthorizerError", 1, "Count", reason=reason, action=action)
