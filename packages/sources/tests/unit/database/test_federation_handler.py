# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the dedicated federation provisioner Lambda."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

MODULE = "coa_sources.database.pipeline.federation_handler"
PROVISIONER = "coa_sources.database.connectors.glue_connection_provisioner"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SOURCES_TABLE", "sources")
    monkeypatch.setenv("SOURCE_SCAN_JOBS_TABLE", "scan-jobs")
    monkeypatch.setenv("SMUS_DOMAIN_ID", "dz-test")
    monkeypatch.setenv("NAMESPACES_TABLE", "namespaces")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.fixture(autouse=True)
def _reset():
    import coa_sources.database.pipeline.federation_handler as mod

    mod._dao = None
    yield
    mod._dao = None


_EVENT = {
    "datasourceId": "DS#abc",
    "sourceId": "abc",
    "namespaceId": "ns-1",
}
_JDBC_ITEM = {
    "sourceSubType": "JDBC_DATABASE",
    "configuration": {
        "engine": "POSTGRESQL",
        "host": "db.example.com",
        "port": 5432,
        "databaseName": "bird",
        "credentialSecretArn": "arn:aws:secretsmanager:us-east-1:123:secret:s-AbCdEf",
    },
}


def _patch_dao(item):
    dao = MagicMock()
    dao.get.return_value = item
    return patch(f"{MODULE}._get_dao", return_value=dao), dao


@pytest.mark.unit
class TestFederationHandler:
    def test_glue_native_grants_lf_and_marks_queryable(self):
        """GLUE_DATABASE sources get an LF native grant instead of catalog provisioning.

        Regression test: accounts with strict LF mode (IAM_ALLOWED_PRINCIPALS removed)
        received PERMISSION_DENIED from Athena because no LF data permission was ever
        granted to the serve runtime role for native Glue tables.
        """
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, dao = _patch_dao({"sourceSubType": "GLUE_DATABASE", "athenaDatabase": "retail_demo"})
        with (
            ctx,
            patch(f"{MODULE}.provision_federated_catalog") as prov,
            patch(f"{MODULE}._consumer_role_arn", return_value="arn:aws:iam::123:role/serve"),
            patch(f"{MODULE}.grant_consumer_select_native", return_value=True) as grant,
        ):
            out = handler(_EVENT)

        prov.assert_not_called()
        grant.assert_called_once_with(
            database_name="retail_demo",
            principal_arn="arn:aws:iam::123:role/serve",
        )
        dao.update.assert_called_once()
        assert dao.update.call_args.kwargs["update_fields"] == {"queryable": True}
        assert out == {"provisioned": False, "reason": "glue-native", "queryable": True}

    def test_skips_non_jdbc_non_glue_source(self):
        """Other source types (e.g. DOCUMENT_SOURCE) are still skipped entirely."""
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, _ = _patch_dao({"sourceSubType": "DOCUMENT_SOURCE"})
        with ctx, patch(f"{MODULE}.provision_federated_catalog") as prov:
            out = handler(_EVENT)
        assert out == {"provisioned": False, "reason": "not-jdbc"}
        prov.assert_not_called()

    def test_glue_native_skips_when_no_athena_database(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, _ = _patch_dao({"sourceSubType": "GLUE_DATABASE"})
        with ctx, patch(f"{MODULE}.grant_consumer_select_native") as grant:
            out = handler(_EVENT)
        assert out == {"provisioned": False, "reason": "no-athena-database"}
        grant.assert_not_called()

    def test_glue_native_grant_failure_writes_queryable_false(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, dao = _patch_dao({"sourceSubType": "GLUE_DATABASE", "athenaDatabase": "retail_demo"})
        with (
            ctx,
            patch(f"{MODULE}._consumer_role_arn", return_value="arn:aws:iam::123:role/serve"),
            patch(f"{MODULE}.grant_consumer_select_native", return_value=False),
        ):
            out = handler(_EVENT)

        # Grant failed → always write queryable=False so stale True from discovery is cleared.
        dao.update.assert_called_once()
        assert dao.update.call_args.kwargs["update_fields"] == {"queryable": False}
        assert out["queryable"] is False

    def test_glue_native_ddb_write_failure_is_swallowed(self):
        """DDB update failure after a successful LF grant does not raise.

        The LF grant is idempotent — even if the DDB write races with a
        concurrent source deletion, the permission persists and a re-scan
        will retry the write. The handler must not raise so the scan pipeline
        does not mark the source SCAN_FAILED.
        """
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, dao = _patch_dao({"sourceSubType": "GLUE_DATABASE", "athenaDatabase": "retail_demo"})
        dao.update.side_effect = RuntimeError("ddb gone")
        with (
            ctx,
            patch(f"{MODULE}._consumer_role_arn", return_value="arn:aws:iam::123:role/serve"),
            patch(f"{MODULE}.grant_consumer_select_native", return_value=True),
        ):
            # Must not raise despite DDB failure.
            out = handler(_EVENT)
        assert out == {"provisioned": False, "reason": "glue-native", "queryable": True}

    def test_skips_incomplete_jdbc_config(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, _ = _patch_dao({"sourceSubType": "JDBC_DATABASE", "configuration": {"engine": "POSTGRESQL"}})
        with ctx, patch(f"{MODULE}.provision_federated_catalog") as prov:
            out = handler(_EVENT)
        assert out["provisioned"] is False
        prov.assert_not_called()

    def test_grant_with_no_discovered_schemas(self):
        from coa_sources.database.pipeline.federation_handler import handler

        # No discoveredSchemas on the record → grant is called with an empty list,
        # which grant_consumer_select treats as a no-op → source stays not-queryable.
        ctx, dao = _patch_dao(_JDBC_ITEM)
        with (
            ctx,
            patch(f"{MODULE}.provision_federated_catalog") as prov,
            patch(f"{MODULE}._consumer_role_arn", return_value="arn:aws:iam::123:role/consumer"),
            patch(f"{MODULE}.grant_consumer_select", return_value=False) as grant,
        ):
            prov.return_value = {"glueConnectionName": "c", "athenaDataCatalogName": "cat"}
            out = handler(_EVENT)
        grant.assert_called_once_with(catalog_name="cat", schemas=[], principal_arn="arn:aws:iam::123:role/consumer")
        assert dao.update.call_args.kwargs["update_fields"]["queryable"] is False
        assert out["queryable"] is False

    def test_skips_when_connector_cannot_read_secret(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, _ = _patch_dao(_JDBC_ITEM)
        with (
            ctx,
            patch(f"{MODULE}._secret_readable_by_connector", return_value=False),
            patch(f"{MODULE}.provision_federated_catalog") as prov,
        ):
            out = handler(_EVENT)
        assert out == {"provisioned": False, "reason": "secret-unreadable"}
        prov.assert_not_called()

    def test_provisions_and_persists(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, dao = _patch_dao(_JDBC_ITEM)
        with (
            ctx,
            patch(f"{MODULE}.provision_federated_catalog") as prov,
            patch(f"{MODULE}.grant_consumer_select", return_value=True),
        ):
            prov.return_value = {"glueConnectionName": "c", "athenaDataCatalogName": "cat"}
            out = handler(_EVENT)
        assert out == {
            "provisioned": True,
            "queryable": True,
            "glueConnectionName": "c",
            "athenaDataCatalogName": "cat",
        }
        prov.assert_called_once()
        dao.update.assert_called_once()
        assert dao.update.call_args.kwargs["update_fields"]["queryable"] is True

    def test_provision_failure_raises(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, dao = _patch_dao(_JDBC_ITEM)
        with (
            ctx,
            patch(f"{MODULE}.provision_federated_catalog", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            handler(_EVENT)
        dao.update.assert_not_called()

    def test_persist_failure_rolls_back_and_raises(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, dao = _patch_dao(_JDBC_ITEM)
        dao.update.side_effect = RuntimeError("ddb down")
        with (
            ctx,
            patch(f"{MODULE}.provision_federated_catalog") as prov,
            patch(f"{MODULE}.grant_consumer_select", return_value=True),
            patch(f"{MODULE}.cleanup_federated_resources") as cleanup,
        ):
            prov.return_value = {"glueConnectionName": "c", "athenaDataCatalogName": "cat"}
            with pytest.raises(RuntimeError, match="ddb down"):
                handler(_EVENT)
        cleanup.assert_called_once_with(glue_connection_name="c", athena_catalog_name="cat")

    def test_grants_lf_select_to_consumer_role(self):
        from coa_sources.database.pipeline.federation_handler import handler

        # Schemas come from discovery's discoveredSchemas, lowercased to match the
        # federated catalog's DB names (CATALOG_CASING_FILTER=LOWERCASE_ONLY).
        ctx, dao = _patch_dao({**_JDBC_ITEM, "discoveredSchemas": ["Public", "Sales"]})
        with (
            ctx,
            patch(f"{MODULE}.provision_federated_catalog") as prov,
            patch(f"{MODULE}._consumer_role_arn", return_value="arn:aws:iam::123:role/consumer"),
            patch(f"{MODULE}.grant_consumer_select", return_value=True) as grant,
        ):
            prov.return_value = {"glueConnectionName": "c", "athenaDataCatalogName": "cat"}
            handler(_EVENT)
        grant.assert_called_once_with(
            catalog_name="cat", schemas=["public", "sales"], principal_arn="arn:aws:iam::123:role/consumer"
        )
        assert dao.update.call_args.kwargs["update_fields"]["queryable"] is True

    def test_not_queryable_when_grant_fails(self):
        from coa_sources.database.pipeline.federation_handler import handler

        ctx, dao = _patch_dao({**_JDBC_ITEM, "discoveredSchemas": ["public"]})
        with (
            ctx,
            patch(f"{MODULE}.provision_federated_catalog") as prov,
            patch(f"{MODULE}._consumer_role_arn", return_value=""),
            patch(f"{MODULE}.grant_consumer_select", return_value=False) as grant,
        ):
            prov.return_value = {"glueConnectionName": "c", "athenaDataCatalogName": "cat"}
            out = handler(_EVENT)
        # No grant (no consumer principal) → provisioned but NOT queryable.
        grant.assert_called_once_with(catalog_name="cat", schemas=["public"], principal_arn="")
        assert dao.update.call_args.kwargs["update_fields"]["queryable"] is False
        assert out["queryable"] is False
