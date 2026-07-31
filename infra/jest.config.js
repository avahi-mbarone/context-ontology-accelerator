// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/test"],
  testMatch: ["**/*.test.ts"],
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { tsconfig: "tsconfig.json" }],
  },
  moduleNameMapper: {
    "^@coa/shared$": "<rootDir>/../libs/ts-shared/src/index.ts",
  },
  collectCoverage: true,
  coverageDirectory: "coverage",
  coverageReporters: ["text", ["cobertura", { file: "coverage.xml" }]],
  collectCoverageFrom: ["lib/**/*.ts", "bin/**/*.ts"],
  coverageThreshold: {
    global: {
      lines: 80,
    },
  },
};
