# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared AOSS vector client (coa_common.opensearch).

Covers the query-body shapes (server-side k-NN filter, count, filter search),
the canonical index mapping, the direct-vs-proxy transport split, and the
transient-retry helpers. ``time.sleep`` is patched so backoff doesn't slow the
suite; no real AOSS is contacted.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from opensearchpy.exceptions import ConnectionError as OSConnectionError
from opensearchpy.exceptions import ConnectionTimeout, RequestError, TransportError
from opensearchpy.helpers.errors import BulkIndexError

pytestmark = pytest.mark.unit

from coa_common.opensearch import (
    AossVectorClient,
    build_index_mapping,
    bulk_with_retry,
    is_transient,
    oss_retry,
)
from coa_common.opensearch import client as client_mod
from coa_common.opensearch import retry as retry_mod


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch.object(retry_mod.time, "sleep", return_value=None):
        yield


# ── Canonical mapping ────────────────────────────────────────────────────


class TestBuildIndexMapping:
    def test_embedding_is_method_less_knn_vector(self):
        m = build_index_mapping(1024)["mappings"]["properties"]
        assert m["embedding"] == {"type": "knn_vector", "dimension": 1024}
        assert "method" not in m["embedding"]  # NEXTGEN rejects method.engine

    def test_filterable_fields_are_keyword(self):
        m = build_index_mapping(768)["mappings"]["properties"]
        keyword_fields = (
            "entity_uri",
            "ontology_id",
            "entity_type",
            "embedding_type",
            "model_id",
            "namespace",
            "data_source_id",
        )
        for f in keyword_fields:
            assert m[f] == {"type": "keyword"}, f

    def test_prompt_fields_are_text(self):
        m = build_index_mapping(1024)["mappings"]["properties"]
        assert m["text"] == {"type": "text"}
        assert m["context_text"] == {"type": "text"}

    def test_knn_setting_enabled(self):
        assert build_index_mapping(1024)["settings"]["index"]["knn"] is True


# ── is_transient / oss_retry / bulk_with_retry ───────────────────────────


class TestIsTransient:
    def test_429_and_5xx_are_transient(self):
        for status in (429, 500, 502, 503, 504):
            assert is_transient(TransportError(status, "x")) is True

    def test_4xx_not_transient(self):
        for status in (400, 403, 404, 409):
            assert is_transient(TransportError(status, "x")) is False

    def test_connection_errors_are_transient(self):
        assert is_transient(OSConnectionError("N/A", "refused", Exception())) is True
        assert is_transient(ConnectionTimeout("t")) is True

    def test_generic_not_transient(self):
        assert is_transient(ValueError("nope")) is False


class TestOssRetry:
    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise TransportError(503, "unavailable")
            return "ok"

        assert oss_retry("op", flaky) == "ok"
        assert calls["n"] == 3

    def test_terminal_raises_immediately(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise RequestError(400, "bad", {})

        with pytest.raises(RequestError):
            oss_retry("op", boom)
        assert calls["n"] == 1

    def test_transient_reraises_on_exhaustion(self):
        """A never-recovering transient fault re-raises the REAL error after
        OSS_MAX_RETRIES+1 attempts (not a swallowed empty result). This is the
        exhaustion path the correctness fix relies on: an exhausted retry must
        propagate so callers fail loud instead of silently degrading."""
        calls = {"n": 0}

        def always_503():
            calls["n"] += 1
            raise TransportError(503, "unavailable")

        with pytest.raises(TransportError):
            oss_retry("op", always_503)
        assert calls["n"] == retry_mod.OSS_MAX_RETRIES + 1


class TestBulkWithRetry:
    def _err(self, items):
        return BulkIndexError(f"{len(items)} failed", items)

    def test_resubmits_only_transiently_failed(self):
        client = MagicMock()
        actions = [
            {"_op_type": "index", "_index": "i", "entity_uri": "a"},
            {"_op_type": "index", "_index": "i", "entity_uri": "b"},
        ]
        failed = self._err([{"index": {"status": 500, "data": {"entity_uri": "b"}}}])
        with patch.object(retry_mod, "bulk", side_effect=[failed, None]) as mock_bulk:
            bulk_with_retry(client, actions)
        assert mock_bulk.call_count == 2
        assert mock_bulk.call_args_list[1].args[1] == [{"_op_type": "index", "_index": "i", "entity_uri": "b"}]

    def test_terminal_item_reraises(self):
        client = MagicMock()
        actions = [{"_op_type": "index", "_index": "i", "entity_uri": "a"}]
        failed = self._err([{"index": {"status": 400, "data": {"entity_uri": "a"}}}])
        with (
            patch.object(retry_mod, "bulk", side_effect=failed) as mock_bulk,
            pytest.raises(BulkIndexError),
        ):
            bulk_with_retry(client, actions)
        assert mock_bulk.call_count == 1

    def test_empty_is_noop(self):
        client = MagicMock()
        with patch.object(retry_mod, "bulk") as mock_bulk:
            bulk_with_retry(client, [])
        mock_bulk.assert_not_called()


# ── AossVectorClient query shapes ────────────────────────────────────────


def _client_with_capture(response):
    """Direct client whose underlying (retry-wrapped) search captures the body."""
    cap = {}
    c = AossVectorClient(endpoint="https://x.aoss.us-west-2.on.aws", region="us-west-2", dimensions=4)

    def _search(index, body):
        cap["index"] = index
        cap["body"] = body
        return response

    # Inject a fake retry-wrapped client exposing .search (bypasses real signing).
    fake = MagicMock()
    fake.search.side_effect = _search
    c._client = fake
    return c, cap


class TestKnnSearch:
    def test_filters_pushed_into_knn_and_exact_top_k(self):
        c, cap = _client_with_capture({"hits": {"hits": [{"_id": "1", "_score": 0.9, "_source": {"entity_uri": "u"}}]}})
        filters = [{"term": {"entity_type": "class"}}, {"exists": {"field": "data_source_id"}}]
        hits = c.knn_search("idx", [0.1] * 4, top_k=5, filters=filters)

        body = cap["body"]
        assert body["size"] == 5
        knn = body["query"]["knn"]["embedding"]
        assert knn["k"] == 5
        assert knn["filter"] == {"bool": {"filter": filters}}
        assert hits[0]["entity_uri"] == "u" and hits[0]["_score"] == 0.9

    def test_no_filters_omits_filter_clause(self):
        c, cap = _client_with_capture({"hits": {"hits": []}})
        c.knn_search("idx", [0.1] * 4, top_k=7)
        knn = cap["body"]["query"]["knn"]["embedding"]
        assert "filter" not in knn and knn["k"] == 7

    def test_short_vector_is_padded(self):
        c, cap = _client_with_capture({"hits": {"hits": []}})
        c.knn_search("idx", [0.1, 0.2], top_k=3)  # dims=4 → padded to 4
        assert cap["body"]["query"]["knn"]["embedding"]["vector"] == [0.1, 0.2, 0.0, 0.0]


class TestCount:
    def test_builds_filter_and_returns_total(self):
        c, cap = _client_with_capture({"hits": {"total": {"value": 3}}})
        n = c.count("idx", filters=[{"exists": {"field": "data_source_id"}}])
        assert n == 3
        assert cap["body"]["size"] == 0
        assert cap["body"]["query"] == {"bool": {"filter": [{"exists": {"field": "data_source_id"}}]}}

    def test_no_filters_uses_match_all(self):
        c, cap = _client_with_capture({"hits": {"total": {"value": 10}}})
        assert c.count("idx") == 10
        assert cap["body"]["query"] == {"match_all": {}}


# ── delete_by_term (delete-then-count-to-zero) ─────────────────────────────


def _delete_client(search_pages, count_seq):
    """Direct client scripted for delete_by_term.

    delete_by_term issues two kinds of ``search`` against the same fake client,
    told apart by ``body["size"]``:
      - ``size == page`` (>0): a delete-page fetch → returns the next id list
        from ``search_pages`` shaped as ``{"hits": {"hits": [{"_id": …}]}}``.
      - ``size == 0``: the terminal ``count`` (a size-0 search) → returns the
        next value from ``count_seq`` shaped as ``{"hits": {"total": {…}}}``.
    ``client.delete`` is a plain MagicMock so call_count / side_effect work.
    """
    c = AossVectorClient(endpoint="https://x.aoss.us-west-2.on.aws", region="us-west-2", dimensions=4)
    searches = iter(search_pages)
    counts = iter(count_seq)

    def _search(index, body):
        if body.get("size") == 0:  # count query
            return {"hits": {"total": {"value": next(counts, 0)}}}
        return {"hits": {"hits": [{"_id": i} for i in next(searches, [])]}}

    fake = MagicMock()
    fake.search.side_effect = _search
    c._client = fake
    return c, fake


class TestDeleteByTerm:
    """Regression: delete must reach a *verified zero* count, not break on a
    single stale-empty ``search`` page. AOSS ``search`` is not read-your-writes
    consistent, so an empty page mid-drain would strand the tail (observed live:
    orphaned property embeddings after an ontology delete). The terminal gate is
    ``count()`` == 0; an empty page must NOT end the loop on its own.
    """

    def test_happy_path_single_pass_to_zero(self):
        c, fake = _delete_client(search_pages=[["a", "b", "c"]], count_seq=[0])
        with patch.object(client_mod.time, "sleep"):
            deleted = c.delete_by_term("idx", "ontology_id", "urn:o")
        assert deleted == 3
        assert fake.delete.call_count == 3

    def test_returns_zero_when_no_hits(self):
        c, fake = _delete_client(search_pages=[[]], count_seq=[0])
        with patch.object(client_mod.time, "sleep"):
            assert c.delete_by_term("idx", "ontology_id", "urn:o") == 0
        fake.delete.assert_not_called()

    def test_does_not_stop_on_stale_empty_search_while_count_nonzero(self):
        # Pass 1: search returns 2 ids (deleted) but count still says 4 (2 more
        #         docs the stale search view hasn't surfaced yet).
        # Pass 2: search returns EMPTY (the buggy code broke here!), count → 2 →
        #         loop MUST continue rather than strand the tail.
        # Pass 3: search returns the last 2 ids (deleted), count → 0 → done.
        c, fake = _delete_client(search_pages=[["a", "b"], [], ["c", "d"]], count_seq=[4, 2, 0])
        with patch.object(client_mod.time, "sleep"):
            deleted = c.delete_by_term("idx", "ontology_id", "urn:o")
        assert deleted == 4  # every matching doc was issued a delete (2 + 0 + 2)
        assert fake.delete.call_count == 4

    def test_swallows_per_doc_delete_errors(self):
        c, fake = _delete_client(search_pages=[["1", "2"]], count_seq=[0])
        fake.delete.side_effect = [None, RuntimeError("gone")]
        with patch.object(client_mod.time, "sleep"):
            # One delete raises; the loop swallows it and only the success counts.
            assert c.delete_by_term("idx", "ontology_id", "urn:o") == 1

    def test_missing_index_on_count_is_treated_as_done(self):
        from opensearchpy.exceptions import NotFoundError

        c = AossVectorClient(endpoint="https://x.aoss.us-west-2.on.aws", region="us-west-2", dimensions=4)
        fake = MagicMock()

        def _search(index, body):
            if body.get("size") == 0:
                raise NotFoundError(404, "index_not_found_exception", {})
            return {"hits": {"hits": []}}

        fake.search.side_effect = _search
        c._client = fake
        with patch.object(client_mod.time, "sleep"):
            assert c.delete_by_term("idx", "ontology_id", "urn:o") == 0

    def test_stall_gives_up_without_infinite_loop(self):
        # search always empty + count never drops → no progress. The no-progress
        # stall deadline must end the loop (this test hangs if it doesn't).
        c, fake = _delete_client(search_pages=[[], [], []], count_seq=[7, 7, 7])
        with (
            patch.object(client_mod.time, "sleep"),
            patch.object(client_mod, "_DELETE_VERIFY_STALL_TIMEOUT_S", 0),
        ):
            deleted = c.delete_by_term("idx", "ontology_id", "urn:o")
        assert deleted == 0  # nothing deletable; returned rather than hung


# ── signed-client auth ─────────────────────────────────────────────────────


class TestSignedClientAuth:
    """The direct client signs with the LIVE boto3 credentials object (not a
    frozen snapshot) so a cached client survives Fargate task-role token
    rotation, using the ``aoss`` service (AWSV4SignerAuth defaults to ``es``)."""

    def test_uses_live_credentials_and_aoss_service(self):
        from coa_common.opensearch import client as client_mod

        fake_creds = object()
        session = MagicMock()
        session.get_credentials.return_value = fake_creds
        with (
            patch.object(client_mod.boto3, "Session", return_value=session),
            patch.object(client_mod, "AWSV4SignerAuth") as mock_auth,
            patch.object(client_mod, "OpenSearch") as mock_os,
        ):
            c = AossVectorClient(endpoint="https://x.aoss.us-west-2.on.aws", region="us-west-2", dimensions=4)
            c.ensure_index("idx")  # forces the signed client to be built
            args = mock_auth.call_args.args
            assert args[0] is fake_creds  # LIVE object, not get_frozen_credentials()
            assert args[1] == "us-west-2"
            assert args[2] == "aoss"
            mock_os.assert_called_once()

    def test_missing_credentials_raises(self):
        from coa_common.opensearch import client as client_mod

        session = MagicMock()
        session.get_credentials.return_value = None
        with patch.object(client_mod.boto3, "Session", return_value=session):
            c = AossVectorClient(endpoint="https://x.aoss.us-west-2.on.aws", region="us-west-2")
            with pytest.raises(RuntimeError, match="credentials"):
                c.ensure_index("idx")


# ── signed-client connection pool ───────────────────────────────────────────


class TestSignedClientPoolSize:
    """The shared client is hit by BOTH induction ThreadPools: first-pass
    grounding recall (INDUCER_GROUNDING_WORKERS, default 24) and second-pass
    column match (INDUCER_COLUMN_MATCH_WORKERS, default 16). ``pool_maxsize`` must
    cover the WIDEST sharer or the wider pass starves ("Connection pool is full")."""

    def _build_and_capture_pool_maxsize(self):
        from coa_common.opensearch import client as client_mod

        session = MagicMock()
        session.get_credentials.return_value = object()
        with (
            patch.object(client_mod.boto3, "Session", return_value=session),
            patch.object(client_mod, "AWSV4SignerAuth"),
            patch.object(client_mod, "OpenSearch") as mock_os,
        ):
            c = AossVectorClient(endpoint="https://x.aoss.us-west-2.on.aws", region="us-west-2", dimensions=4)
            c.ensure_index("idx")  # forces the signed client to be built
            return mock_os.call_args.kwargs["pool_maxsize"]

    def test_defaults_honor_wider_grounding_width(self, monkeypatch):
        monkeypatch.delenv("INDUCER_COLUMN_MATCH_WORKERS", raising=False)
        monkeypatch.delenv("INDUCER_GROUNDING_WORKERS", raising=False)
        # grounding default (24) > column-match default (16) → grounding wins.
        assert self._build_and_capture_pool_maxsize() == 24

    def test_grounding_width_wins_when_wider(self, monkeypatch):
        monkeypatch.setenv("INDUCER_COLUMN_MATCH_WORKERS", "16")
        monkeypatch.setenv("INDUCER_GROUNDING_WORKERS", "40")
        assert self._build_and_capture_pool_maxsize() == 40

    def test_column_match_width_wins_when_wider(self, monkeypatch):
        monkeypatch.setenv("INDUCER_COLUMN_MATCH_WORKERS", "32")
        monkeypatch.setenv("INDUCER_GROUNDING_WORKERS", "24")
        assert self._build_and_capture_pool_maxsize() == 32

    def test_floor_of_ten_when_both_smaller(self, monkeypatch):
        monkeypatch.setenv("INDUCER_COLUMN_MATCH_WORKERS", "4")
        monkeypatch.setenv("INDUCER_GROUNDING_WORKERS", "8")
        assert self._build_and_capture_pool_maxsize() == 10


# ── transport split ──────────────────────────────────────────────────────


class TestTransportSplit:
    def test_proxy_client_routes_search_through_transport(self):
        seen = {}

        def transport(action, index, body):
            seen["action"] = action
            seen["index"] = index
            return {"hits": {"hits": [{"_id": "1", "_score": 0.5, "_source": {"entity_uri": "u"}}]}}

        c = AossVectorClient(transport=transport, dimensions=4)
        assert c.is_proxy is True
        hits = c.knn_search("idx", [0.1] * 4, top_k=2, filters=[{"term": {"entity_type": "class"}}])
        assert seen["action"] == "search" and seen["index"] == "idx"
        assert hits[0]["entity_uri"] == "u"

    def test_proxy_client_writes_raise(self):
        c = AossVectorClient(transport=lambda a, i, b: {}, dimensions=4)
        with pytest.raises(RuntimeError):
            c.bulk_index("idx", [{"entity_uri": "a"}])
        with pytest.raises(RuntimeError):
            c.ensure_index("idx")

    def test_direct_client_without_endpoint_raises(self):
        c = AossVectorClient(dimensions=4)  # no endpoint, no transport
        with pytest.raises(RuntimeError):
            c.ensure_index("idx")
