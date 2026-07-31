// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount any component rendered by a test after it finishes. Without this,
// happy-dom accumulates every test's DOM in one document, so a test that
// asserts the ABSENCE of text (e.g. `queryByText(...).toBeNull()`) can match a
// leaked node from an earlier test's render and flake under parallel load.
afterEach(() => {
  cleanup();
});
