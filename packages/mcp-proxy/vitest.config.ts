// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "cobertura"],
      reportsDirectory: "coverage",
      include: ["src/**/*.ts"],
      // index.ts's pure helpers (findUvx/buildPath) are unit-tested; its main()
      // stdio-bridge (spawns uvx, wires process signals) is v8-ignored inline.
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },
  },
});
