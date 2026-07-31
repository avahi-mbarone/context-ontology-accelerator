// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// @examples for com.amazon.semanticcontext.grant operations.
// Extracted from the service definition to keep operation/shape
// definitions readable. `apply` merges the @examples trait back onto
// each operation, so the doc-coverage gate in linters.smithy still holds.
$version: "2"

namespace com.amazon.semanticcontext.grant

apply CreateGrant @examples([
    {
        title: "Grant a user the editor role on a namespace"
        input: {
            namespaceId: "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
            body: {
                principalType: "User"
                principalId: "alice@example.com"
                role: "namespace-editor"
                tableAllowlist: ["sales.orders", "sales.customers"]
                columnDenylist: {
                    "sales.customers": ["ssn", "email"]
                }
                allowedMetrics: ["total_revenue"]
            }
        }
        output: {
            grant: {
                grantId: "01HZY8K3M4N5P6Q7R8S9T0V1W2"
                namespaceId: "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
                principalType: "User"
                principalId: "alice@example.com"
                role: "namespace-editor"
                grantedBy: "admin@example.com"
                grantedAt: "2026-01-15T10:30:00Z"
                tableAllowlist: ["sales.orders", "sales.customers"]
                columnDenylist: {
                    "sales.customers": ["ssn", "email"]
                }
                allowedMetrics: ["total_revenue"]
            }
        }
    }
])

apply ListNamespaceGrants @examples([
    {
        title: "List grants in a namespace"
        input: { namespaceId: "3f2504e0-4f89-41d3-9a0c-0305e82c3301", maxResults: 25 }
        output: {
            grants: [
                {
                    grantId: "01HZY8K3M4N5P6Q7R8S9T0V1W2"
                    namespaceId: "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
                    principalType: "User"
                    principalId: "alice@example.com"
                    role: "namespace-editor"
                    grantedBy: "admin@example.com"
                    grantedAt: "2026-01-15T10:30:00Z"
                }
            ]
            nextToken: "eyJvZmZzZXQiOjI1fQ=="
        }
    }
])

apply DeleteGrant @examples([
    {
        title: "Delete a namespace grant"
        input: { namespaceId: "3f2504e0-4f89-41d3-9a0c-0305e82c3301", grantId: "01HZY8K3M4N5P6Q7R8S9T0V1W2" }
        output: {}
    }
])

apply ListPrincipalGrants @examples([
    {
        title: "List all grants for a principal"
        input: { principalId: "alice@example.com" }
        output: {
            grants: [
                {
                    grantId: "01HZY8K3M4N5P6Q7R8S9T0V1W2"
                    namespaceId: "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
                    principalType: "User"
                    principalId: "alice@example.com"
                    role: "namespace-editor"
                    grantedBy: "admin@example.com"
                    grantedAt: "2026-01-15T10:30:00Z"
                }
            ]
        }
    }
])

apply CreatePlatformGrant @examples([
    {
        title: "Grant a group the platform-admin role"
        input: {
            body: { principalType: "Group", principalId: "platform-operators", role: "platform-admin" }
        }
        output: {
            grant: { grantId: "01HZY8K3M4N5P6Q7R8S9T0V1W2", principalType: "Group", principalId: "platform-operators", role: "platform-admin", grantedBy: "admin@example.com", grantedAt: "2026-01-15T10:30:00Z" }
        }
    }
])

apply ListPlatformGrants @examples([
    {
        title: "List platform grants"
        input: { maxResults: 25 }
        output: {
            grants: [
                {
                    grantId: "01HZY8K3M4N5P6Q7R8S9T0V1W2"
                    principalType: "Group"
                    principalId: "platform-operators"
                    role: "platform-admin"
                    grantedBy: "admin@example.com"
                    grantedAt: "2026-01-15T10:30:00Z"
                }
            ]
            nextToken: "eyJvZmZzZXQiOjI1fQ=="
        }
    }
])

apply DeletePlatformGrant @examples([
    {
        title: "Delete a platform grant"
        input: { grantId: "01HZY8K3M4N5P6Q7R8S9T0V1W2" }
        output: {}
    }
])
