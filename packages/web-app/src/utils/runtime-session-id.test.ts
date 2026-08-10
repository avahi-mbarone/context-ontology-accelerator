// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { deriveRuntimeSessionId } from "./runtime-session-id";

describe("deriveRuntimeSessionId", () => {
  it("returns undefined for a missing sub", () => {
    expect(deriveRuntimeSessionId(undefined)).toBeUndefined();
  });

  it("pads a short sub (e.g. Midway username) to the 33-char minimum", () => {
    const result = deriveRuntimeSessionId("noahpaig");
    expect(result).toBeDefined();
    expect(result!.length).toBeGreaterThanOrEqual(33);
    expect(result!.startsWith("noahpaig")).toBe(true);
  });

  it("returns a Cognito-style UUID sub unchanged (already ≥33 chars)", () => {
    const uuidSub = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"; // 36 chars
    expect(deriveRuntimeSessionId(uuidSub)).toBe(uuidSub);
  });

  it("is deterministic — same sub always maps to the same session id", () => {
    expect(deriveRuntimeSessionId("noahpaig")).toBe(
      deriveRuntimeSessionId("noahpaig"),
    );
  });
});
