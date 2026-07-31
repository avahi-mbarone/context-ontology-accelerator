# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the combined metric API router (metric_api_handler)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def _event(method: str, resource: str, *, name: str | None = None) -> dict:
    path_params: dict[str, str] = {"namespaceId": "ns-1"}
    if name is not None:
        path_params["name"] = name
    return {"httpMethod": method, "resource": resource, "pathParameters": path_params}


class TestOsiRouting:
    """OSI import/export routes must dispatch to their dedicated handlers."""

    def test_upload_url_route_dispatches_to_upload_url_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "get_osi_upload_url_handler", return_value={"ok": "upload"}) as h:
            result = metric_api_handler.handler(
                _event("POST", "/namespaces/{namespaceId}/metrics/import-osi/upload-url"), None
            )

        assert result == {"ok": "upload"}
        h.assert_called_once()

    def test_import_osi_route_dispatches_to_import_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "import_osi_handler", return_value={"ok": "import"}) as h:
            result = metric_api_handler.handler(_event("POST", "/namespaces/{namespaceId}/metrics/import-osi"), None)

        assert result == {"ok": "import"}
        h.assert_called_once()

    def test_export_osi_route_dispatches_to_export_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "export_osi_handler", return_value={"ok": "export"}) as h:
            result = metric_api_handler.handler(_event("GET", "/namespaces/{namespaceId}/metrics/export-osi"), None)

        assert result == {"ok": "export"}
        h.assert_called_once()

    def test_import_jobs_route_dispatches_to_get_import_job_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "get_import_job_handler", return_value={"ok": "job"}) as h:
            result = metric_api_handler.handler(
                _event("GET", "/namespaces/{namespaceId}/metrics/import-jobs/{jobId}"), None
            )

        assert result == {"ok": "job"}
        h.assert_called_once()

    def test_bulk_delete_route_dispatches_to_bulk_delete_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "bulk_delete_handler", return_value={"ok": "bulk"}) as h:
            result = metric_api_handler.handler(
                _event("POST", "/namespaces/{namespaceId}/metrics/bulk-delete-metrics"), None
            )

        assert result == {"ok": "bulk"}
        h.assert_called_once()


class TestCrudRouting:
    """CRUD + validate routes must dispatch by method and presence of {name}."""

    def test_validate_route_dispatches_to_validate_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "validate_handler", return_value={"ok": "validate"}) as h:
            result = metric_api_handler.handler(_event("POST", "/namespaces/{namespaceId}/metrics/validate"), None)

        assert result == {"ok": "validate"}
        h.assert_called_once()

    def test_post_dispatches_to_create_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "create_handler", return_value={"ok": "create"}) as h:
            result = metric_api_handler.handler(_event("POST", "/namespaces/{namespaceId}/metrics"), None)

        assert result == {"ok": "create"}
        h.assert_called_once()

    def test_get_with_name_dispatches_to_get_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "get_handler", return_value={"ok": "get"}) as h:
            result = metric_api_handler.handler(
                _event("GET", "/namespaces/{namespaceId}/metrics/{name}", name="revenue"), None
            )

        assert result == {"ok": "get"}
        h.assert_called_once()

    def test_get_without_name_dispatches_to_list_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "list_handler", return_value={"ok": "list"}) as h:
            result = metric_api_handler.handler(_event("GET", "/namespaces/{namespaceId}/metrics"), None)

        assert result == {"ok": "list"}
        h.assert_called_once()

    def test_put_with_name_dispatches_to_update_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "update_handler", return_value={"ok": "update"}) as h:
            result = metric_api_handler.handler(
                _event("PUT", "/namespaces/{namespaceId}/metrics/{name}", name="revenue"), None
            )

        assert result == {"ok": "update"}
        h.assert_called_once()

    def test_delete_with_name_dispatches_to_delete_handler(self):
        from coa_metrics.api import metric_api_handler

        with patch.object(metric_api_handler, "delete_handler", return_value={"ok": "delete"}) as h:
            result = metric_api_handler.handler(
                _event("DELETE", "/namespaces/{namespaceId}/metrics/{name}", name="revenue"), None
            )

        assert result == {"ok": "delete"}
        h.assert_called_once()


class TestMethodNotAllowed:
    """Unmatched method/path combinations return 405."""

    def test_unmatched_method_returns_405(self):
        from coa_metrics.api import metric_api_handler

        result = metric_api_handler.handler(_event("PATCH", "/namespaces/{namespaceId}/metrics"), None)

        assert result["statusCode"] == 405
        assert result["headers"]["Allow"] == "GET, POST, PUT, DELETE"
        assert json.loads(result["body"])["message"] == "Method not allowed"

    def test_put_without_name_is_not_allowed(self):
        from coa_metrics.api import metric_api_handler

        # PUT requires a metric name; without one it falls through to 405.
        result = metric_api_handler.handler(_event("PUT", "/namespaces/{namespaceId}/metrics"), None)

        assert result["statusCode"] == 405

    def test_delete_without_name_is_not_allowed(self):
        from coa_metrics.api import metric_api_handler

        result = metric_api_handler.handler(_event("DELETE", "/namespaces/{namespaceId}/metrics"), None)

        assert result["statusCode"] == 405
