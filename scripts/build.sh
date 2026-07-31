#!/usr/bin/env sh
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Building all packages via Nx ==="
pnpm nx run-many -t build

# Docker images (if any)
echo ""
echo "=== Building Docker Images ==="
find "$REPO_ROOT/packages" -name "Dockerfile" -type f | while read -r dockerfile; do
    pkg_dir="$(dirname "$dockerfile")"
    pkg_name="$(basename "$pkg_dir")"
    image_name="coa-${pkg_name}:latest"

    echo "Building $image_name from $pkg_dir..."
    docker build -t "$image_name" "$pkg_dir"
    echo "✓ $image_name built"
    echo ""
done

echo "=== All builds complete ==="
