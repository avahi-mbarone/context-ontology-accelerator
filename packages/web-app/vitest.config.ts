// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@coa/shared": path.resolve(__dirname, "../../libs/ts-shared/src/index.ts"),
      "@auth": path.resolve(__dirname, "src/auth"),
      "@app-types": path.resolve(__dirname, "src/app-types"),
      "@api-hooks": path.resolve(__dirname, "src/api-hooks"),
      "@components": path.resolve(__dirname, "src/components"),
      "@pages": path.resolve(__dirname, "src/pages"),
      "@utils": path.resolve(__dirname, "src/utils"),
      "@constants": path.resolve(__dirname, "src/constants"),
    },
  },
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: "./vitest-setup.ts",
    css: false,
    // Coverage config lives HERE, not in vite.config.ts. Vitest resolves
    // vitest.config.ts with priority over vite.config.ts and does NOT merge
    // them, so a `coverage` block placed in vite.config.ts is never applied
    // when `vitest run --coverage` executes — the gate was silently dead.
    // (ORR QAL-A-2.)
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "cobertura"],
      reportsDirectory: "coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/**/index.ts",
        "src/App.tsx",
        "src/app-types/**",
        "src/components/Chat/index.tsx",
        "src/pages/index.ts",
        "src/utils/index.ts",
      ],
      // Enforced floor at current measured coverage. This gate was previously
      // DEAD — it lived in vite.config.ts, which Vitest resolves but does not
      // load when vitest.config.ts exists, so `vitest run --coverage` never
      // applied it. Relocating it here makes it real. Ratchet toward the 80%
      // ORR target (QAL-A-2) as component/hook tests are added; never lower.
      thresholds: {
        lines: 58,
        statements: 58,
        functions: 58,
        branches: 70,
      },
    },
    // Playwright E2E specs live under tests/e2e and use their own runner; keep
    // Vitest from discovering them (they call test.describe from
    // @playwright/test, which throws under Vitest). Vitest's default excludes
    // (node_modules, dist, etc.) are inlined here since we override the option.
    exclude: [
      "**/node_modules/**",
      "**/dist/**",
      "**/cypress/**",
      "**/.{idea,git,cache,output,temp}/**",
      "**/{karma,rollup,webpack,vite,vitest,jest,ava,babel,nyc,cypress,tsup,build,eslint,prettier}.config.*",
      "tests/e2e/**",
    ],
    server: {
      deps: {
        // Bundle Cloudscape components that use ESM directory imports
        // incompatible with Node's native ESM resolution in happy-dom.
        inline: [/@cloudscape-design\/.*/],
      },
    },
  },
});
