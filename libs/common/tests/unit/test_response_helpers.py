# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for response.iso_to_epoch and get_caller_identity."""

from __future__ import annotations

import calendar
import datetime

import pytest
from coa_common.response import get_caller_identity, iso_to_epoch

pytestmark = pytest.mark.unit


class TestIsoToEpoch:
    def test_parses_iso_with_z_suffix(self):
        result = iso_to_epoch("2024-01-01T00:00:00Z")
        expected = calendar.timegm(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC).utctimetuple())
        assert result == expected

    def test_parses_iso_with_offset(self):
        result = iso_to_epoch("2024-01-01T02:00:00+02:00")
        # 02:00 at +02:00 == 00:00 UTC
        assert result == calendar.timegm(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC).utctimetuple())

    def test_non_string_returned_unchanged(self):
        assert iso_to_epoch(12345) == 12345

    def test_unparseable_string_returned_unchanged(self):
        assert iso_to_epoch("not-a-date") == "not-a-date"


class TestGetCallerIdentity:
    def test_custom_authorizer_email_preferred(self):
        event = {"requestContext": {"authorizer": {"email": "a@b.com", "userId": "u1"}}}
        assert get_caller_identity(event) == "a@b.com"

    def test_custom_authorizer_falls_back_to_user_id(self):
        event = {"requestContext": {"authorizer": {"userId": "u1"}}}
        assert get_caller_identity(event) == "u1"

    def test_custom_authorizer_falls_back_to_principal_id(self):
        event = {"requestContext": {"authorizer": {"principalId": "p1"}}}
        assert get_caller_identity(event) == "p1"

    def test_cognito_claims_email(self):
        event = {"requestContext": {"authorizer": {"claims": {"email": "c@d.com", "sub": "sub-1"}}}}
        assert get_caller_identity(event) == "c@d.com"

    def test_cognito_claims_sub_fallback(self):
        event = {"requestContext": {"authorizer": {"claims": {"sub": "sub-1"}}}}
        assert get_caller_identity(event) == "sub-1"

    def test_iam_identity_user_arn(self):
        event = {"requestContext": {"identity": {"userArn": "arn:aws:iam::123:user/x"}}}
        assert get_caller_identity(event) == "arn:aws:iam::123:user/x"

    def test_unknown_when_no_identity(self):
        assert get_caller_identity({}) == "unknown"
        assert get_caller_identity({"requestContext": {"authorizer": {}}}) == "unknown"
