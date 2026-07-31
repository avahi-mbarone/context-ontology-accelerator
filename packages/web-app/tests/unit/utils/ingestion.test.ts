// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import {
  ingestionStatusType,
  isActiveStatus,
} from "../../../src/utils/ingestion";
import { formatTimestamp } from "../../../src/utils/helpers";

describe("ingestionStatusType", () => {
  it("returns success for completed", () => {
    expect(ingestionStatusType("completed")).toBe("success");
  });

  it("returns error for failed", () => {
    expect(ingestionStatusType("failed")).toBe("error");
  });

  it("returns in-progress for ingesting", () => {
    expect(ingestionStatusType("ingesting")).toBe("in-progress");
  });

  it("returns pending for pending", () => {
    expect(ingestionStatusType("pending")).toBe("pending");
  });

  it("returns stopped for unknown status", () => {
    expect(ingestionStatusType("unknown")).toBe("stopped");
    expect(ingestionStatusType(undefined)).toBe("stopped");
  });
});

describe("formatTimestamp", () => {
  it("returns em dash for undefined", () => {
    expect(formatTimestamp(undefined)).toBe("—");
  });

  it("formats a Date object", () => {
    const d = new Date("2025-01-15T10:30:00Z");
    const result = formatTimestamp(d);
    expect(result).toContain("2025");
  });

  it("formats a date string", () => {
    const result = formatTimestamp("2025-06-01T00:00:00Z");
    expect(result).toContain("2025");
  });
});

describe("isActiveStatus", () => {
  it("returns true for pending", () => {
    expect(isActiveStatus("pending")).toBe(true);
  });

  it("returns true for ingesting", () => {
    expect(isActiveStatus("ingesting")).toBe(true);
  });

  it("returns false for completed", () => {
    expect(isActiveStatus("completed")).toBe(false);
  });

  it("returns false for failed", () => {
    expect(isActiveStatus("failed")).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(isActiveStatus(undefined)).toBe(false);
  });
});
