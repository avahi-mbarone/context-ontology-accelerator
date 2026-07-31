// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// @examples for com.amazon.semanticcontext operations.
// Extracted from the service definition to keep operation/shape
// definitions readable. `apply` merges the @examples trait back onto
// each operation, so the doc-coverage gate in linters.smithy still holds.
$version: "2"

namespace com.amazon.semanticcontext

apply HealthCheck @examples([
    {
        title: "Service is healthy"
        input: {}
        output: { status: "ok" }
    }
])

apply GetSystemHealth @examples([
    {
        title: "All subsystems healthy"
        input: {}
        output: {
            status: "ok"
            ontologyInduction: { graphStore: "ok", vectorStore: "ok", bedrockEmbeddings: "ok", descriptionLlm: "ok" }
            dynamodb: "ok"
            neptuneKg: "ok"
            opensearch: "ok"
        }
    }
])
