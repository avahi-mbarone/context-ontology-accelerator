# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for shared namespace-teardown cleanup primitives (cleanup.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from coa_common.constants import RESOURCE_PREFIX

MODULE = "coa_control_plane.namespace.cleanup"


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("NAMESPACES_TABLE", "test-namespaces")
    monkeypatch.setenv("RESOURCE_ROLE_MAPPINGS_TABLE", "test-rrm")
    monkeypatch.setenv("ROLES_TABLE", "test-roles")
    monkeypatch.setenv("DATAZONE_DOMAIN_ID", "dz-domain-123")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.mark.unit
class TestDeleteNamespaceRecordsTransaction:
    """Tests for the atomic DDB transaction step."""

    def test_transact_write_includes_namespace_and_reservation(self):
        with patch(f"{MODULE}.boto3") as mock_boto:
            mock_ddb = MagicMock()
            mock_boto.client.return_value = mock_ddb

            from coa_control_plane.namespace.cleanup import delete_namespace_records

            delete_namespace_records("ns-123", "sales")

        mock_ddb.transact_write_items.assert_called_once()
        items = mock_ddb.transact_write_items.call_args.kwargs["TransactItems"]
        assert len(items) == 2
        assert items[0]["Delete"]["Key"]["PK"]["S"] == "NS#ns-123"
        assert items[1]["Delete"]["Key"]["PK"]["S"] == "NS_NAME#sales"

    def test_transact_write_without_name(self):
        with patch(f"{MODULE}.boto3") as mock_boto:
            mock_ddb = MagicMock()
            mock_boto.client.return_value = mock_ddb

            from coa_control_plane.namespace.cleanup import delete_namespace_records

            delete_namespace_records("ns-123", None)

        items = mock_ddb.transact_write_items.call_args.kwargs["TransactItems"]
        assert len(items) == 1  # Only namespace record, no reservation


@pytest.mark.unit
class TestDeleteSmuProject:
    """delete_smu_project must force-delete the DataZone project (skipDeletionCheck)."""

    def test_delete_project_passes_skip_deletion_check(self, monkeypatch):
        """Regression: every induced namespace owns DataZone assets, so delete_project
        must pass skipDeletionCheck=True or it raises ValidationException and the whole
        namespace deletion fails (lands in DELETE_FAILED)."""
        from coa_control_plane.namespace import cleanup

        mock_dz = MagicMock()
        monkeypatch.setattr(cleanup.boto3, "client", lambda *a, **k: mock_dz)

        cleanup.delete_smu_project("ns-123", {"dataZoneProjectId": "proj-abc"})

        mock_dz.delete_project.assert_called_once_with(
            domainIdentifier="dz-domain-123", identifier="proj-abc", skipDeletionCheck=True
        )

    def test_skips_when_no_project_or_domain(self, monkeypatch):
        from coa_control_plane.namespace import cleanup

        mock_dz = MagicMock()
        monkeypatch.setattr(cleanup.boto3, "client", lambda *a, **k: mock_dz)
        # No dataZoneProjectId → early return, no DataZone call.
        cleanup.delete_smu_project("ns-123", {})
        mock_dz.delete_project.assert_not_called()

    def test_assumes_project_access_role_when_configured(self, monkeypatch):
        """DataZone authorizes DeleteProject against project membership, not
        IAM policy alone — DzProjectAccessRole is a registered project
        member/owner, so this Lambda's own execution-role credentials must
        never be used directly for the call when a role ARN is configured."""
        from coa_control_plane.namespace import cleanup

        monkeypatch.setenv("PROJECT_ACCESS_ROLE_ARN", "arn:aws:iam::123456789012:role/dz-project-access")

        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIAFAKE",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }
        mock_dz = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_dz

        def _client(service, **kwargs):
            assert service == "sts"
            return mock_sts

        monkeypatch.setattr(cleanup.boto3, "client", _client)
        monkeypatch.setattr(cleanup.boto3, "Session", lambda **kwargs: mock_session)

        cleanup.delete_smu_project("ns-123", {"dataZoneProjectId": "proj-abc"})

        mock_sts.assume_role.assert_called_once_with(
            RoleArn="arn:aws:iam::123456789012:role/dz-project-access",
            RoleSessionName="ns-deletion-platform-dz-access",
        )
        mock_dz.delete_project.assert_called_once_with(
            domainIdentifier="dz-domain-123", identifier="proj-abc", skipDeletionCheck=True
        )

    def test_falls_back_to_execution_role_when_no_role_arn_configured(self, monkeypatch):
        """No PROJECT_ACCESS_ROLE_ARN configured (e.g. local/unit-test envs) —
        must not attempt to assume anything, just use the caller's own
        credentials as before."""
        from coa_control_plane.namespace import cleanup

        monkeypatch.delenv("PROJECT_ACCESS_ROLE_ARN", raising=False)

        mock_dz = MagicMock()
        mock_sts = MagicMock()

        def _client(service, **kwargs):
            return mock_sts if service == "sts" else mock_dz

        monkeypatch.setattr(cleanup.boto3, "client", _client)

        cleanup.delete_smu_project("ns-123", {"dataZoneProjectId": "proj-abc"})

        mock_sts.assume_role.assert_not_called()
        mock_dz.delete_project.assert_called_once_with(
            domainIdentifier="dz-domain-123", identifier="proj-abc", skipDeletionCheck=True
        )


@pytest.mark.unit
class TestDeleteAthenaWorkgroup:
    def test_skips_when_no_workgroup_name(self, monkeypatch):
        from coa_control_plane.namespace import cleanup

        mock_athena = MagicMock()
        monkeypatch.setattr(cleanup.boto3, "client", lambda *a, **k: mock_athena)

        cleanup.delete_athena_workgroup(None)

        mock_athena.delete_work_group.assert_not_called()

    def test_deletes_workgroup(self, monkeypatch):
        from coa_control_plane.namespace import cleanup

        mock_athena = MagicMock()
        monkeypatch.setattr(cleanup.boto3, "client", lambda *a, **k: mock_athena)

        cleanup.delete_athena_workgroup(f"{RESOURCE_PREFIX}-dev-sales")

        mock_athena.delete_work_group.assert_called_once_with(
            WorkGroup=f"{RESOURCE_PREFIX}-dev-sales", RecursiveDeleteOption=True
        )


@pytest.mark.unit
class TestDeleteRoleMappingsAndRoles:
    def test_delete_role_mappings_no_table_configured_noop(self, monkeypatch):
        monkeypatch.delenv("RESOURCE_ROLE_MAPPINGS_TABLE", raising=False)
        from coa_control_plane.namespace import cleanup

        with patch(f"{MODULE}._delete_all_by_index") as mock_delete:
            cleanup.delete_role_mappings("ns-123")

        mock_delete.assert_not_called()

    def test_delete_role_mappings_queries_namespace_grants_index(self):
        from coa_control_plane.namespace import cleanup

        with patch(f"{MODULE}._delete_all_by_index") as mock_delete:
            cleanup.delete_role_mappings("ns-123")

        mock_delete.assert_called_once_with("test-rrm", "NamespaceGrantsIndex", "namespaceKey", "NS#ns-123")

    def test_delete_roles_queries_by_pk(self):
        from coa_control_plane.namespace import cleanup

        with patch(f"{MODULE}._delete_all_by_pk") as mock_delete:
            cleanup.delete_roles("ns-123")

        mock_delete.assert_called_once_with("test-roles", "NS#ns-123")
