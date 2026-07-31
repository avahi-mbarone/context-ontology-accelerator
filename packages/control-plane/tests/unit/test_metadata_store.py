# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for coa_control_plane.ssm_config."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from coa_control_plane.ssm_config import get_smus_domain_id


@pytest.mark.unit
class TestGetSMUSDomainId:
    @patch("coa_control_plane.ssm_config.boto3")
    def test_returns_domain_id(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "dzd_domain123"}}
        mock_boto3.client.return_value = mock_ssm

        result = get_smus_domain_id("/coa")

        assert result == "dzd_domain123"
        mock_ssm.get_parameter.assert_called_once_with(Name="/coa/smus/domain-id")

    @patch("coa_control_plane.ssm_config.boto3")
    def test_raises_on_missing_value(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {}}
        mock_boto3.client.return_value = mock_ssm

        with pytest.raises(ValueError, match="not found at SSM parameter"):
            get_smus_domain_id("/coa")

    @patch("coa_control_plane.ssm_config.boto3")
    def test_raises_on_empty_value(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": ""}}
        mock_boto3.client.return_value = mock_ssm

        with pytest.raises(ValueError, match="not found at SSM parameter"):
            get_smus_domain_id("/coa")

    @patch("coa_control_plane.ssm_config.boto3")
    def test_propagates_ssm_errors(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "not found"}},
            "GetParameter",
        )
        mock_boto3.client.return_value = mock_ssm

        with pytest.raises(ClientError):
            get_smus_domain_id("/coa")
