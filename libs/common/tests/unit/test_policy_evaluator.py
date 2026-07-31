# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for coa_authorization.policy_evaluator and cedar_schema."""

from __future__ import annotations

import pytest
from coa_authorization.cedar_schema import DATA_SCHEMA, SCL_SCHEMA, Action, EntityType
from coa_authorization.policy_evaluator import (
    build_resource_entity,
    build_user_entity,
    evaluate,
    load_seed_policies,
    load_seed_policy,
)

pytestmark = pytest.mark.unit


class TestCedarSchema:
    def test_entity_types_are_scl_namespaced(self):
        assert EntityType.NAMESPACE == "SCL::Namespace"
        assert EntityType.USER == "SCL::User"
        assert EntityType.SOURCE == "SCL::Source"

    def test_actions_are_scl_namespaced(self):
        assert Action.VIEW_NAMESPACE == "SCL::Action::viewNamespace"
        assert Action.MANAGE_NAMESPACE == "SCL::Action::manageNamespace"

    def test_schema_prefix_constant(self):
        assert SCL_SCHEMA == "SCL"

    def test_data_schema_loaded_from_json(self):
        assert isinstance(DATA_SCHEMA, dict)
        assert DATA_SCHEMA  # non-empty


class TestLoadSeedPolicies:
    def test_load_seed_policies_returns_concatenated_text(self):
        policies = load_seed_policies()
        assert isinstance(policies, str)
        assert "permit" in policies
        # Concatenation of multiple seed files
        assert policies.count("permit") > 1

    def test_load_seed_policy_returns_single_named_policy(self):
        text = load_seed_policy("global_admin")
        assert "platform-admin" in text
        assert "permit" in text


class TestBuildEntities:
    def test_build_user_entity_defaults_empty_roles(self):
        entity = build_user_entity("user-42")
        assert entity["uid"] == {"type": "SCL::User", "id": "user-42"}
        assert entity["attrs"]["globalRoles"] == []
        assert entity["attrs"]["resourceRoles"] == []

    def test_build_user_entity_carries_roles(self):
        entity = build_user_entity(
            "user-42",
            global_roles=["platform-admin"],
            resource_roles=[{"role": "namespace-owner", "resourceUID": "ns-1"}],
        )
        assert entity["attrs"]["globalRoles"] == ["platform-admin"]
        assert entity["attrs"]["resourceRoles"] == [{"role": "namespace-owner", "resourceUID": "ns-1"}]

    def test_build_resource_entity_defaults_only_id(self):
        entity = build_resource_entity("Namespace", "ns-1")
        assert entity["uid"] == {"type": "SCL::Namespace", "id": "ns-1"}
        assert entity["attrs"] == {"id": "ns-1"}

    def test_build_resource_entity_merges_extra_attrs(self):
        entity = build_resource_entity("Source", "src-1", attrs={"namespace": "ns-1"})
        assert entity["attrs"] == {"id": "src-1", "namespace": "ns-1"}


class TestEvaluate:
    def test_platform_admin_allowed_to_view(self):
        result = evaluate(
            policies=load_seed_policies(),
            user_id="u1",
            action="viewNamespace",
            resource_type="Namespace",
            resource_id="ns-1",
            global_roles=["platform-admin"],
        )
        assert result.allowed is True

    def test_no_roles_denied_to_manage(self):
        result = evaluate(
            policies=load_seed_policies(),
            user_id="u2",
            action="manageNamespace",
            resource_type="Namespace",
            resource_id="ns-1",
        )
        assert result.allowed is False

    def test_platform_viewer_can_list(self):
        result = evaluate(
            policies=load_seed_policies(),
            user_id="u3",
            action="list",
            resource_type="Namespace",
            resource_id="ns-1",
            global_roles=["platform-viewer"],
        )
        assert result.allowed is True

    def test_namespace_owner_scoped_to_own_resource(self):
        result = evaluate(
            policies=load_seed_policies(),
            user_id="owner",
            action="manageSource",
            resource_type="Source",
            resource_id="ns-1",
            resource_roles=[{"role": "namespace-owner", "resourceUID": "ns-1"}],
        )
        assert result.allowed is True

    def test_archived_namespace_guard_forbids_mutation_even_for_admin(self):
        """The forbid guard overrides platform-admin when namespace is not ACTIVE."""
        result = evaluate(
            policies=load_seed_policies(),
            user_id="u1",
            action="manageNamespace",
            resource_type="Namespace",
            resource_id="ns-1",
            global_roles=["platform-admin"],
            context={"namespaceStatus": "ARCHIVED"},
        )
        assert result.allowed is False

    def test_active_namespace_permits_admin_mutation(self):
        result = evaluate(
            policies=load_seed_policies(),
            user_id="u1",
            action="manageNamespace",
            resource_type="Namespace",
            resource_id="ns-1",
            global_roles=["platform-admin"],
            context={"namespaceStatus": "ACTIVE"},
        )
        assert result.allowed is True

    def test_malformed_policy_fails_closed(self):
        """Any evaluation error returns an explicit deny (fail-closed)."""
        result = evaluate(
            policies="this is not valid cedar!!!",
            user_id="u",
            action="list",
            resource_type="Namespace",
            resource_id="ns",
        )
        assert result.allowed is False
