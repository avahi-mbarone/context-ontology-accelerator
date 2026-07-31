# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the SMUS catalog source path in induce_catalog.

Covers ``_fetch_catalog_from_smus`` which replaces the HTTP sidecar fetch
when ``CATALOG_SOURCE=smus`` is set. The function is a thin wrapper over
``read_approved_catalog`` from libs/common, so the tests focus on:

* Argument plumbing into ``read_approved_catalog``
* Filtering the returned ``sources`` list by ``datasourceId``
* Empty-databases fallback when the datasource is missing from the result

Also exercises a few lightweight helpers in ``induce_catalog`` that were
previously uncovered (HTTP fetch + identifier-casing utilities).
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from coa_ontology.induce_catalog import (
    _fetch_catalog,
    _fetch_catalog_from_smus,
)
from coa_ontology.inducer.strategies.base import (
    to_camel as _to_camel,
)
from coa_ontology.inducer.strategies.base import (
    to_pascal as _to_pascal,
)
from coa_ontology.inducer.strategies.base import (
    xsd_for as _xsd_for,
)
from rdflib import XSD

pytestmark = pytest.mark.unit


def _config(extra: dict | None = None) -> dict:
    base = {
        "smus_domain_id": "dzd-test",
        "namespaces_table": "namespaces-table",
        "smus_datasources_table": "datasources-table",
        "smus_region": "us-west-2",
    }
    if extra:
        base.update(extra)
    return base


def _patch_resolve_project_id(project_id: str = "prj-test", namespace_id: str = "ns-test"):
    """Stub the DDB-backed dataZoneProjectId lookup."""
    return patch(
        "coa_ontology.induce_catalog._resolve_datazone_project_id",
        return_value=(project_id, namespace_id),
    )


class TestFetchCatalogFromSmus:
    def test_returns_matching_source(self):
        """When read_approved_catalog returns the requested datasource, the
        source dict is returned unchanged."""
        expected_source = {
            "datasourceId": "ds-abc",
            "databases": [{"name": "db1", "tables": []}],
        }
        result = {"sources": [expected_source]}

        with (
            _patch_resolve_project_id(),
            patch(
                "coa_common.metadata_store.catalog_reader.read_approved_catalog",
                return_value=result,
            ) as mock_read,
        ):
            got = _fetch_catalog_from_smus(_config(), "ds-abc", namespace="ns-test")

        assert got == expected_source
        mock_read.assert_called_once_with(
            domain_id="dzd-test",
            project_id="prj-test",
            namespace_id="ns-test",
            data_source_ids=["ds-abc"],
            datasources_table="datasources-table",
            region="us-west-2",
        )

    def test_filters_by_datasource_id(self):
        """Only the source whose datasourceId matches is returned, even if
        the call returns multiple sources."""
        target = {"datasourceId": "ds-target", "databases": [{"name": "t"}]}
        other = {"datasourceId": "ds-other", "databases": [{"name": "o"}]}
        result = {"sources": [other, target]}

        with (
            _patch_resolve_project_id(),
            patch(
                "coa_common.metadata_store.catalog_reader.read_approved_catalog",
                return_value=result,
            ),
        ):
            got = _fetch_catalog_from_smus(_config(), "ds-target", namespace="ns-test")

        assert got == target

    def test_returns_empty_databases_when_datasource_missing(self):
        """If the requested datasource is not in the result, fall back to an
        empty-databases shape so downstream code sees zero tables instead of
        crashing."""
        result = {"sources": [{"datasourceId": "ds-other", "databases": []}]}

        with (
            _patch_resolve_project_id(),
            patch(
                "coa_common.metadata_store.catalog_reader.read_approved_catalog",
                return_value=result,
            ),
        ):
            got = _fetch_catalog_from_smus(_config(), "ds-missing", namespace="ns-test")

        assert got == {"databases": []}

    def test_returns_empty_databases_when_sources_missing(self):
        """A result with no ``sources`` key still returns the empty fallback
        rather than raising KeyError."""
        with (
            _patch_resolve_project_id(),
            patch(
                "coa_common.metadata_store.catalog_reader.read_approved_catalog",
                return_value={},
            ),
        ):
            got = _fetch_catalog_from_smus(_config(), "ds-x", namespace="ns-test")

        assert got == {"databases": []}

    def test_uses_aws_region_when_smus_region_omitted(self, monkeypatch):
        """``smus_region`` falls back to ``AWS_REGION`` env var (or default)."""
        cfg = _config()
        del cfg["smus_region"]
        monkeypatch.setenv("AWS_REGION", "us-west-2")

        with (
            _patch_resolve_project_id(),
            patch(
                "coa_common.metadata_store.catalog_reader.read_approved_catalog",
                return_value={"sources": []},
            ) as mock_read,
        ):
            _fetch_catalog_from_smus(cfg, "ds-x", namespace="ns-test")

        kwargs = mock_read.call_args.kwargs
        # Falls back to AWS_REGION env var when smus_region is unset.
        assert kwargs["region"] == "us-west-2"


class TestFetchCatalogHttp:
    """Coverage for the HTTP path used when ``CATALOG_SOURCE != smus``."""

    def test_passes_url_and_returns_json_body(self):
        fake_payload = {"databases": [{"name": "db1", "tables": []}]}

        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_payload
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(httpx, "Client", return_value=mock_client):
            got = _fetch_catalog("http://catalog:8003", "ds-1")

        assert got == fake_payload
        mock_client.get.assert_called_once_with("http://catalog:8003/api/v1/catalogs/ds-1")
        mock_resp.raise_for_status.assert_called_once()


class TestIdentifierHelpers:
    """Lightweight casing helpers used while building proposal ontologies."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("policy_holder", "PolicyHolder"),
            ("policy-holder", "PolicyHolder"),
            ("CLAIM", "Claim"),
            ("", "Entity"),
            ("a", "A"),
        ],
    )
    def test_to_pascal(self, raw, expected):
        assert _to_pascal(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("policy_holder", "policyHolder"),
            ("Claim_id", "claimId"),
            ("", "entity"),
            ("a", "a"),
        ],
    )
    def test_to_camel(self, raw, expected):
        assert _to_camel(raw) == expected

    @pytest.mark.parametrize(
        "sql_type,expected",
        [
            ("VARCHAR(255)", XSD.string),
            ("INT", XSD.integer),
            ("BIGINT", XSD.long),
            ("DECIMAL(10,2)", XSD.decimal),
            ("BOOLEAN", XSD.boolean),
            ("UNKNOWN_TYPE", XSD.string),  # fallback to string
        ],
    )
    def test_xsd_for_known_and_unknown(self, sql_type, expected):
        assert _xsd_for(sql_type) == expected
