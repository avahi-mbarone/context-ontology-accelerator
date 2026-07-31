# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for AthenaQueryExecutor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from coa_common.constants import RESOURCE_PREFIX
from coa_serve.clients.athena import AthenaQueryExecutor
from coa_serve.tier2.sql_firewall import UnsafeSQLError


@pytest.mark.unit
class TestAthenaValidation:
    """Test namespace validation and SQL safety (via centralized firewall)."""

    def _make_executor(self):
        with patch("boto3.client"), patch("boto3.resource"):
            return AthenaQueryExecutor(region="us-east-1", sources_table="test-sources")

    def test_validates_namespace(self):
        from coa_serve.query_utils import validate_namespace

        validate_namespace("my-namespace")
        validate_namespace("test_ns")
        validate_namespace("demo123")

        with pytest.raises(ValueError):
            validate_namespace("invalid namespace!")
        with pytest.raises(ValueError):
            validate_namespace("ns with spaces")

    def test_workgroup_prefix(self):
        with patch("boto3.client"), patch("boto3.resource"):
            executor = AthenaQueryExecutor(workgroup_prefix="coa-", sources_table="t")
        assert executor._workgroup_prefix == "coa-"


@pytest.mark.unit
class TestAthenaExecution:
    """Test query execution (mocked boto3)."""

    async def test_execute_success(self):
        with patch("boto3.client") as mock_boto:
            mock_athena = MagicMock()
            mock_boto.return_value = mock_athena

            mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-123"}
            mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
            mock_athena.get_query_results.return_value = {
                "ResultSet": {
                    "ResultSetMetadata": {
                        "ColumnInfo": [
                            {"Name": "id"},
                            {"Name": "name"},
                        ]
                    },
                    "Rows": [
                        {"Data": [{"VarCharValue": "id"}, {"VarCharValue": "name"}]},  # header
                        {"Data": [{"VarCharValue": "1"}, {"VarCharValue": "Alice"}]},
                        {"Data": [{"VarCharValue": "2"}, {"VarCharValue": "Bob"}]},
                    ],
                }
            }

            with patch("boto3.resource"):
                executor = AthenaQueryExecutor(region="us-east-1", sources_table="t")
            result = await executor.execute(
                "SELECT id, name FROM users",
                namespace="demo",
                database="mydb",
            )

            assert result.row_count == 2
            assert result.columns == ["id", "name"]
            assert result.rows[0]["id"] == "1"
            assert result.rows[0]["name"] == "Alice"
            assert result.truncated is False

    async def test_invalid_timeout_raises(self):
        with patch("boto3.client"), patch("boto3.resource"):
            executor = AthenaQueryExecutor(region="us-east-1", sources_table="t")

        with pytest.raises(ValueError, match="timeout_seconds must be 1-300"):
            await executor.execute(
                "SELECT 1",
                namespace="demo",
                timeout_seconds=0,
            )

        with pytest.raises(ValueError, match="timeout_seconds must be 1-300"):
            await executor.execute(
                "SELECT 1",
                namespace="demo",
                timeout_seconds=400,
            )

    async def test_invalid_sql_raises(self):
        with patch("boto3.client"), patch("boto3.resource"):
            executor = AthenaQueryExecutor(region="us-east-1", sources_table="t")

        with pytest.raises(UnsafeSQLError):
            await executor.execute(
                "DROP TABLE users",
                namespace="demo",
            )


@pytest.mark.unit
class TestTableNameRewrite:
    """Test _rewrite_table_names_for_federation."""

    def test_strips_schema_prefix_and_quotes(self):
        result = AthenaQueryExecutor._rewrite_table_names_for_federation(
            "SELECT COUNT(*) AS v0 FROM BIRD_PUBLIC_INCOME AS V1", "public"
        )
        assert '"income"' in result
        assert "BIRD_PUBLIC_INCOME" not in result

    def test_handles_multiple_tables(self):
        sql = "SELECT a.id, b.name FROM BIRD_PUBLIC_INCOME AS a JOIN BIRD_PUBLIC_MAJOR AS b ON a.id = b.id"
        result = AthenaQueryExecutor._rewrite_table_names_for_federation(sql, "public")
        assert '"income"' in result
        assert '"major"' in result
        assert "BIRD_PUBLIC" not in result

    def test_no_match_leaves_sql_unchanged(self):
        sql = "SELECT 1 FROM some_table"
        result = AthenaQueryExecutor._rewrite_table_names_for_federation(sql, "public")
        assert "some_table" in result

    def test_preserves_column_references(self):
        sql = "SELECT V1.AMOUNT FROM BIRD_PUBLIC_INCOME AS V1 WHERE V1.AMOUNT > 100"
        result = AthenaQueryExecutor._rewrite_table_names_for_federation(sql, "public")
        assert '"income"' in result
        assert "AMOUNT" in result or "amount" in result.lower()

    def test_invalid_sql_returns_original(self):
        sql = "NOT VALID SQL {{{"
        result = AthenaQueryExecutor._rewrite_table_names_for_federation(sql, "public")
        assert result == sql


@pytest.mark.unit
class TestFederatedCatalogResolution:
    """Test that federated catalog sources route correctly."""

    async def test_federated_source_uses_discovered_schemas(self):
        """When athenaDataCatalogName + discoveredSchemas set, uses first discovered schema."""
        import json

        with patch("boto3.client") as mock_boto, patch("boto3.resource") as mock_res:
            mock_athena = MagicMock()
            mock_boto.return_value = mock_athena
            mock_table = MagicMock()
            mock_res.return_value.Table.return_value = mock_table

            mock_table.query.return_value = {
                "Items": [
                    {
                        "sourceType": "DATABASE",
                        "athenaDataCatalogName": "scldevds_abc123",
                        "discoveredSchemas": ["public", "analytics"],
                        "queryable": True,
                        "configuration": json.dumps({"schemaName": "ignored"}),
                    }
                ]
            }
            mock_table.get_item.return_value = {"Item": {"athenaWorkgroupName": f"{RESOURCE_PREFIX}-dev-ns-123"}}
            mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-fed"}
            mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
            mock_athena.get_query_results.return_value = {
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": "cnt"}]},
                    "Rows": [
                        {"Data": [{"VarCharValue": "cnt"}]},
                        {"Data": [{"VarCharValue": "42"}]},
                    ],
                }
            }

            executor = AthenaQueryExecutor(region="us-west-2", sources_table="coa-sources", sources_registry=None)
            executor._sources._table_name = "coa-sources"

        result = await executor.execute(
            "SELECT COUNT(*) FROM BIRD_PUBLIC_INCOME",
            namespace="ns-123",
        )

        call_kwargs = mock_athena.start_query_execution.call_args[1]
        assert call_kwargs["QueryExecutionContext"]["Catalog"] == "scldevds_abc123"
        assert call_kwargs["QueryExecutionContext"]["Database"] == "public"
        assert '"income"' in call_kwargs["QueryString"]
        assert result.row_count == 1

    async def test_not_queryable_source_falls_back(self):
        """When queryable is explicitly False, falls back to default database."""
        import json

        with patch("boto3.client") as mock_boto, patch("boto3.resource") as mock_res:
            mock_athena = MagicMock()
            mock_boto.return_value = mock_athena
            mock_table = MagicMock()
            mock_res.return_value.Table.return_value = mock_table

            mock_table.query.return_value = {
                "Items": [
                    {
                        "sourceType": "DATABASE",
                        "athenaDataCatalogName": "scldevds_abc123",
                        "queryable": False,
                        "configuration": json.dumps({}),
                    }
                ]
            }
            mock_table.get_item.return_value = {"Item": None}
            mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-nq"}
            mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
            mock_athena.get_query_results.return_value = {
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                    "Rows": [{"Data": [{"VarCharValue": "x"}]}],
                }
            }

            with patch.dict("os.environ", {"ATHENA_DATABASE": "fallback_db"}):
                executor = AthenaQueryExecutor(region="us-west-2", sources_table="coa-sources")

        await executor.execute("SELECT 1 as x", namespace="ns-123")

        call_kwargs = mock_athena.start_query_execution.call_args[1]
        assert call_kwargs["QueryExecutionContext"]["Database"] == "fallback_db"
        assert call_kwargs["QueryExecutionContext"]["Catalog"] == "AwsDataCatalog"

    async def test_glue_source_uses_athena_database(self):
        """Glue native source uses athenaDatabase field."""
        import json

        with patch("boto3.client") as mock_boto, patch("boto3.resource") as mock_res:
            mock_athena = MagicMock()
            mock_boto.return_value = mock_athena
            mock_table = MagicMock()
            mock_res.return_value.Table.return_value = mock_table

            mock_table.get_item.return_value = {
                "Item": {
                    "sourceType": "DATABASE",
                    "sourceSubType": "GLUE_DATABASE",
                    "athenaDatabase": "my_glue_db",
                    "queryable": True,
                    "configuration": json.dumps({"databaseName": "ignored"}),
                }
            }
            mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-g"}
            mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
            mock_athena.get_query_results.return_value = {
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                    "Rows": [{"Data": [{"VarCharValue": "x"}]}],
                }
            }

            executor = AthenaQueryExecutor(region="us-west-2", sources_table="coa-sources")

        await executor.execute("SELECT 1", namespace="ns-123", data_source_id="src-glue")

        call_kwargs = mock_athena.start_query_execution.call_args[1]
        assert call_kwargs["QueryExecutionContext"]["Database"] == "my_glue_db"
        assert call_kwargs["QueryExecutionContext"]["Catalog"] == "AwsDataCatalog"


@pytest.mark.unit
class TestAthenaDatabaseResolution:
    """Test per-namespace database resolution via SourcesRegistry."""

    async def test_uses_resolved_database_from_ddb(self):
        """When data_source_id resolves to a database, that database is used in the query."""
        import json

        with patch("boto3.client") as mock_boto, patch("boto3.resource") as mock_res:
            mock_athena = MagicMock()
            mock_boto.return_value = mock_athena
            mock_table = MagicMock()
            mock_res.return_value.Table.return_value = mock_table

            mock_table.get_item.return_value = {
                "Item": {"configuration": json.dumps({"databaseName": "bird_test_db_catalog"})}
            }
            mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-1"}
            mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
            mock_athena.get_query_results.return_value = {
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": "count"}]},
                    "Rows": [
                        {"Data": [{"VarCharValue": "count"}]},
                        {"Data": [{"VarCharValue": "42"}]},
                    ],
                }
            }

            executor = AthenaQueryExecutor(region="us-west-2", sources_table="coa-sources")

        await executor.execute(
            "SELECT count(*) as count FROM bird_public_claim",
            namespace="ns-123",
            data_source_id="src-456",
        )

        call_kwargs = mock_athena.start_query_execution.call_args[1]
        assert call_kwargs["QueryExecutionContext"]["Database"] == "bird_test_db_catalog"

    async def test_falls_back_to_env_var_when_ddb_empty(self):
        """When DDB lookup returns nothing, falls back to ATHENA_DATABASE env var."""
        with patch("boto3.client") as mock_boto, patch("boto3.resource") as mock_res:
            mock_athena = MagicMock()
            mock_boto.return_value = mock_athena
            mock_table = MagicMock()
            mock_res.return_value.Table.return_value = mock_table

            mock_table.get_item.return_value = {"Item": None}
            mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-2"}
            mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
            mock_athena.get_query_results.return_value = {
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                    "Rows": [{"Data": [{"VarCharValue": "x"}]}],
                }
            }

            with patch.dict("os.environ", {"ATHENA_DATABASE": "fallback_db"}):
                executor = AthenaQueryExecutor(region="us-west-2", sources_table="coa-sources")

            await executor.execute(
                "SELECT 1 as x",
                namespace="ns-123",
                data_source_id="missing-source",
            )

        call_kwargs = mock_athena.start_query_execution.call_args[1]
        assert call_kwargs["QueryExecutionContext"]["Database"] == "fallback_db"

    async def test_explicit_database_param_skips_ddb(self):
        """When database param is passed explicitly, DDB is not queried."""
        with patch("boto3.client") as mock_boto, patch("boto3.resource") as mock_res:
            mock_athena = MagicMock()
            mock_boto.return_value = mock_athena
            mock_table = MagicMock()
            mock_res.return_value.Table.return_value = mock_table

            mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-3"}
            mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
            mock_athena.get_query_results.return_value = {
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                    "Rows": [{"Data": [{"VarCharValue": "x"}]}],
                }
            }

            executor = AthenaQueryExecutor(region="us-west-2", sources_table="coa-sources")

        await executor.execute(
            "SELECT 1 as x",
            namespace="ns-123",
            database="explicit_db",
        )

        call_kwargs = mock_athena.start_query_execution.call_args[1]
        assert call_kwargs["QueryExecutionContext"]["Database"] == "explicit_db"
        mock_table.get_item.assert_not_called()
