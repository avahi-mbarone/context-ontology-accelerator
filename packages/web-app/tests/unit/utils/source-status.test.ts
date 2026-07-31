// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { sourceStatusType, sourceStatusLabel } from "@utils/source-status";

describe("sourceStatusType", () => {
  it("returns success for APPROVED and COMPLETED", () => {
    expect(sourceStatusType("APPROVED")).toBe("success");
    expect(sourceStatusType("COMPLETED")).toBe("success");
  });

  it("returns error for failure states", () => {
    expect(sourceStatusType("SCAN_FAILED")).toBe("error");
    expect(sourceStatusType("DELETE_FAILED")).toBe("error");
    expect(sourceStatusType("APPROVAL_FAILED")).toBe("error");
    expect(sourceStatusType("REJECTION_FAILED")).toBe("error");
  });

  it("returns stopped for DELETED and REJECTED", () => {
    expect(sourceStatusType("DELETED")).toBe("stopped");
    expect(sourceStatusType("REJECTED")).toBe("stopped");
  });

  it("returns in-progress for transient states", () => {
    expect(sourceStatusType("SCANNING")).toBe("in-progress");
    expect(sourceStatusType("ENRICHING")).toBe("in-progress");
    expect(sourceStatusType("APPROVING")).toBe("in-progress");
    expect(sourceStatusType("REJECTING")).toBe("in-progress");
  });

  it("returns info for unknown statuses", () => {
    expect(sourceStatusType("UNKNOWN")).toBe("info");
    expect(sourceStatusType(undefined)).toBe("info");
  });
});

describe("sourceStatusLabel", () => {
  it("returns formatted labels for all known statuses", () => {
    expect(sourceStatusLabel("APPROVED")).toBe("Approved");
    expect(sourceStatusLabel("REJECTED")).toBe("Rejected");
    expect(sourceStatusLabel("PENDING_REVIEW")).toBe("Pending review");
    expect(sourceStatusLabel("SCAN_FAILED")).toBe("Scan failed");
    expect(sourceStatusLabel("APPROVAL_FAILED")).toBe("Approval failed");
    expect(sourceStatusLabel("REJECTION_FAILED")).toBe("Rejection failed");
  });

  it("returns the raw value for unknown statuses", () => {
    expect(sourceStatusLabel("SOMETHING_ELSE")).toBe("SOMETHING_ELSE");
  });

  it("returns dash for undefined", () => {
    expect(sourceStatusLabel(undefined)).toBe("—");
  });
});
