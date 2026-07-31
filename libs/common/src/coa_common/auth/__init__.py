# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Authentication utilities — token authorizer ABC and implementations."""

from coa_common.auth.cognito_authorizer import CognitoTokenAuthorizer
from coa_common.auth.oidc_authorizer import OIDCTokenAuthorizer
from coa_common.auth.token_authorizer import (
    TokenAuthorizer,
    TokenType,
    TokenValidationResult,
)

__all__ = [
    "CognitoTokenAuthorizer",
    "OIDCTokenAuthorizer",
    "TokenAuthorizer",
    "TokenType",
    "TokenValidationResult",
]
