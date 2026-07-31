// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// @examples for com.amazon.semanticcontext.role operations.
// Extracted from the service definition to keep operation/shape
// definitions readable. `apply` merges the @examples trait back onto
// each operation, so the doc-coverage gate in linters.smithy still holds.
$version: "2"

namespace com.amazon.semanticcontext.role

apply ListPlatformRoles @examples([
    {
        title: "List platform roles"
        input: {}
        output: {
            roles: [
                {
                    roleId: "01H8XGJWBWBAQ4Z2X3Y5N6P7Q"
                    name: "platform-admin"
                    description: "Full administrative access across the platform."
                    scope: "PLATFORM"
                    isBuiltIn: true
                }
            ]
        }
    }
])

apply ListNamespaceRoles @examples([
    {
        title: "List namespace roles"
        input: { namespaceId: "550e8400-e29b-41d4-a716-446655440000" }
        output: {
            roles: [
                {
                    roleId: "01H8XGJWBWBAQ4Z2X3Y5N6P7Q"
                    name: "namespace-admin"
                    description: "Manage all resources within the namespace."
                    scope: "NAMESPACE"
                    isBuiltIn: true
                }
            ]
        }
    }
])

apply GetNamespaceRole @examples([
    {
        title: "Get a namespace role"
        input: { namespaceId: "550e8400-e29b-41d4-a716-446655440000", roleId: "01H8XGJWBWBAQ4Z2X3Y5N6P7Q" }
        output: {
            role: { roleId: "01H8XGJWBWBAQ4Z2X3Y5N6P7Q", name: "namespace-admin", description: "Manage all resources within the namespace.", scope: "NAMESPACE", isBuiltIn: true, cedarPolicy: "permit(principal, action, resource);" }
        }
    }
])
