#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Start SSM port-forward tunnel to the BIRD PostgreSQL database.
#
# This tunnel is required for gold SQL execution during benchmark runs.
# It connects through the bastion host (from the integ-test-databases CDK stack)
# to the Aurora PostgreSQL cluster.
#
# Usage:
#   ./benchmark/tunnel.sh              # uses defaults from CloudFormation
#   ./benchmark/tunnel.sh --background # run in background, write PID to .tunnel.pid
#
# Prerequisites:
#   - AWS CLI v2 with Session Manager plugin installed
#   - Valid AWS credentials with ssm:StartSession permission
#   - The coa-integ-test-databases stack deployed
#
# The tunnel exposes the PostgreSQL cluster on localhost:15432.

set -euo pipefail

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
STACK_NAME="${BENCH_STACK:-coa-integ-test-databases}"
LOCAL_PORT="${BENCH_DB_PORT:-15432}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Resolve bastion instance ID and RDS endpoint from CloudFormation ─────────

echo "🔍 Resolving infrastructure from stack: ${STACK_NAME}..."

OUTPUTS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs" \
    --output json 2>/dev/null) || {
    echo "❌ Could not describe stack '${STACK_NAME}'. Is it deployed?"
    echo "   Deploy with: cd tests/cdk && cdk deploy"
    exit 1
}

BASTION_ID=$(echo "$OUTPUTS" | {
    if command -v jq &>/dev/null; then
        jq -r '.[] | select(.OutputKey == "BastionInstanceId") | .OutputValue'
    else
        python3 -c "
import json, sys
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == 'BastionInstanceId':
        print(o['OutputValue'])
        break
"
    fi
})

PG_ENDPOINT=$(echo "$OUTPUTS" | {
    if command -v jq &>/dev/null; then
        jq -r '.[] | select(.OutputKey == "PgClusterEndpoint") | .OutputValue'
    else
        python3 -c "
import json, sys
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == 'PgClusterEndpoint':
        print(o['OutputValue'])
        break
"
    fi
})

if [[ -z "$BASTION_ID" || -z "$PG_ENDPOINT" ]]; then
    echo "❌ Could not resolve BastionInstanceId or PgClusterEndpoint from stack outputs."
    echo "   Found outputs:"
    echo "$OUTPUTS" | {
        if command -v jq &>/dev/null; then
            jq -r '.[] | "   \(.OutputKey): \(.OutputValue)"'
        else
            python3 -c "
import json, sys
outputs = json.load(sys.stdin)
for o in outputs:
    print(f\"   {o['OutputKey']}: {o['OutputValue']}\")
"
        fi
    }
    exit 1
fi

echo "   Bastion:  ${BASTION_ID}"
echo "   RDS Host: ${PG_ENDPOINT}"
echo "   Local:    localhost:${LOCAL_PORT}"
echo ""

# ─── Check if tunnel already running ─────────────────────────────────────────

PID_FILE="${SCRIPT_DIR}/.tunnel.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "✅ Tunnel already running (PID ${OLD_PID}) on localhost:${LOCAL_PORT}."
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# ─── Start tunnel ────────────────────────────────────────────────────────────

CMD=(
    aws ssm start-session
    --target "$BASTION_ID"
    --document-name AWS-StartPortForwardingSessionToRemoteHost
    --parameters "{\"host\":[\"${PG_ENDPOINT}\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}"
    --region "$REGION"
)

if [[ "${1:-}" == "--background" ]]; then
    echo "🚀 Starting tunnel in background..."
    "${CMD[@]}" &>/dev/null &
    TUNNEL_PID=$!
    echo "$TUNNEL_PID" > "$PID_FILE"
    # Wait a moment for it to establish
    sleep 3
    if kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "✅ Tunnel running (PID ${TUNNEL_PID}), localhost:${LOCAL_PORT} → ${PG_ENDPOINT}:5432"
        echo "   Stop with: kill ${TUNNEL_PID} (or make benchmark-tunnel-stop)"
    else
        echo "❌ Tunnel process exited unexpectedly. Check AWS credentials and SSM plugin."
        rm -f "$PID_FILE"
        exit 1
    fi
else
    echo "🚀 Starting tunnel (Ctrl+C to stop)..."
    echo "   localhost:${LOCAL_PORT} → ${PG_ENDPOINT}:5432"
    echo ""
    exec "${CMD[@]}"
fi
