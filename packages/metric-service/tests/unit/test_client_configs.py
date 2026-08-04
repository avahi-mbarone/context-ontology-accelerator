# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""metric-service shared clients carry retry/timeout config.

The OpenSearch/AOSS retry+timeout now lives in the shared
``coa_common.opensearch.AossVectorClient`` (transient-fault retry
via ``oss_retry``), so metric-service no longer builds its own opensearch-py
client. The Neptune SPARQL path here is still metric-service-owned, so its
split connect/read timeout is asserted below.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.unit


def test_metric_neptune_split_timeout():
    from coa_metrics import neptune_client as nc

    assert isinstance(nc.NEPTUNE_HTTP_TIMEOUT, httpx.Timeout)
    assert nc.NEPTUNE_HTTP_TIMEOUT.connect == 2.0
    assert nc.NEPTUNE_HTTP_TIMEOUT.read == nc.NEPTUNE_TIMEOUT
