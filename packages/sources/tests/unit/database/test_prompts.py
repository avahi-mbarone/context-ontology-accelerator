# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for prompts module."""

from __future__ import annotations

from coa_common.domain_models import BusinessMetadata, Column
from coa_sources.database.enrichment.prompts import SYSTEM_PROMPT, build_user_prompt


class TestBuildUserPrompt:
    def test_basic_prompt(self) -> None:
        columns = [
            Column(name="id", data_type="bigint"),
            Column(name="name", data_type="varchar(255)"),
        ]
        result = build_user_prompt("users", "public", columns)

        assert "Table: public.users" in result
        assert "id (bigint)" in result
        assert "name (varchar(255))" in result

    def test_empty_columns(self) -> None:
        result = build_user_prompt("empty_table", "db", [])

        assert "Table: db.empty_table" in result
        assert "Columns:" in result

    def test_many_columns(self) -> None:
        columns = [Column(name=f"col_{i}", data_type="int") for i in range(100)]
        result = build_user_prompt("big_table", "warehouse", columns)

        assert "col_0 (int)" in result
        assert "col_99 (int)" in result

    def test_extra_context_not_present_by_default(self) -> None:
        columns = [Column(name="id", data_type="bigint")]
        result = build_user_prompt("t", "db", columns)
        assert "External evidence" not in result

    def test_extra_context_appended_when_provided(self) -> None:
        columns = [Column(name="id", data_type="bigint")]
        result = build_user_prompt("t", "db", columns, extra_context="Currency values are EUR or CZK")
        assert "External evidence:" in result
        assert "Currency values are EUR or CZK" in result

    def test_extra_context_hint_appended_after_evidence(self) -> None:
        columns = [Column(name="id", data_type="bigint")]
        result = build_user_prompt(
            "t",
            "db",
            columns,
            extra_context="Some evidence",
            extra_context_hint="Use this to infer FKs",
        )
        assert "External evidence:" in result
        assert "Instructions for evidence:" in result
        assert "Use this to infer FKs" in result
        evidence_pos = result.index("External evidence")
        hint_pos = result.index("Instructions for evidence")
        assert hint_pos > evidence_pos

    def test_extra_context_hint_ignored_without_context(self) -> None:
        columns = [Column(name="id", data_type="bigint")]
        result = build_user_prompt("t", "db", columns, extra_context_hint="Should not appear")
        assert "Instructions for evidence" not in result

    def test_extra_context_after_existing_metadata(self) -> None:
        columns = [Column(name="id", data_type="bigint")]
        result = build_user_prompt(
            "t",
            "db",
            columns,
            existing_description="A table",
            extra_context="Some evidence",
        )
        existing_pos = result.index("Existing metadata")
        evidence_pos = result.index("External evidence")
        assert evidence_pos > existing_pos

    def test_column_source_description_included_in_prompt(self) -> None:
        columns = [
            Column(name="id", data_type="bigint"),
            Column(
                name="status",
                data_type="varchar",
                business_metadata=BusinessMetadata(description="Order fulfillment status"),
            ),
        ]
        result = build_user_prompt("orders", "db", columns)

        assert "id (bigint)" in result
        assert "status (varchar)  -- Order fulfillment status" in result

    def test_column_source_description_flagged_as_existing(self) -> None:
        columns = [
            Column(name="id", data_type="bigint"),
            Column(
                name="status",
                data_type="varchar",
                business_metadata=BusinessMetadata(description="Order status"),
            ),
        ]
        result = build_user_prompt("orders", "db", columns)

        assert "columns_with_descriptions: ['status']" in result


class TestSystemPrompt:
    def test_system_prompt_contains_json_structure(self) -> None:
        assert "table" in SYSTEM_PROMPT
        assert "primary_key" in SYSTEM_PROMPT
        assert "columns" in SYSTEM_PROMPT
        assert "description" in SYSTEM_PROMPT
        assert "synonyms" in SYSTEM_PROMPT
        assert "confidence" in SYSTEM_PROMPT

    def test_system_prompt_instructs_json_only(self) -> None:
        assert "ONLY with raw JSON" in SYSTEM_PROMPT

    def test_system_prompt_has_evidence_rule(self) -> None:
        assert "External evidence" in SYSTEM_PROMPT
