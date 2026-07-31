// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mocks for router + the underlying history hook.
const mockParams = vi.fn();
const mockLocation = vi.fn();
vi.mock("react-router-dom", () => ({
  useParams: () => mockParams(),
  useLocation: () => mockLocation(),
}));

const mockUseSessionHistory = vi.fn();
vi.mock("./use-session-history", () => ({
  useSessionHistory: (...args: unknown[]) => mockUseSessionHistory(...args),
}));

import { useTraceData } from "./use-trace-data";

function historyReturn(over: Partial<Record<string, unknown>> = {}) {
  return { data: null, loading: false, error: null, retry: vi.fn(), ...over };
}

describe("useTraceData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockParams.mockReturnValue({ sessionId: "s1", requestId: "r1" });
    mockLocation.mockReturnValue({ key: "k1", state: null });
    mockUseSessionHistory.mockReturnValue(historyReturn());
  });

  it("resolves from router state when a message with a response is present", () => {
    mockLocation.mockReturnValue({
      key: "k1",
      state: {
        query: "who are the customers?",
        message: {
          content: "Answer text",
          requestId: "rX",
          response: {
            result: {
              trace: [{ step: "tier1" }],
              tier: 1,
              queryUsed: "SELECT 1",
              sparqlGenerated: "ASK {}",
              guardrailBlocked: false,
              metadata: { foo: "bar" },
              confidence: { score: 0.9, rationale: "high" },
            },
          },
        },
      },
    });

    const { result } = renderHook(() => useTraceData());

    expect(result.current.data).not.toBeNull();
    expect(result.current.data?.tier).toBe(1);
    expect(result.current.data?.content).toBe("Answer text");
    expect(result.current.data?.userQuery).toBe("who are the customers?");
    // requestId param wins over message.requestId
    expect(result.current.data?.requestId).toBe("r1");
    expect(result.current.data?.metadata).toEqual({ foo: "bar" });
    // When router state resolves, the history hook is called with undefined args (no fetch).
    expect(mockUseSessionHistory).toHaveBeenCalledWith(undefined, undefined);
  });

  it("falls back to live trace steps when result.trace is absent", () => {
    mockLocation.mockReturnValue({
      key: "k2",
      state: {
        message: {
          content: "c",
          liveTraceSteps: [{ step: "live" }],
          response: { result: { tier: 2 } },
        },
      },
    });
    const { result } = renderHook(() => useTraceData());
    expect(result.current.data?.trace).toEqual([{ step: "live" }]);
    expect(result.current.data?.userQuery).toBe("—"); // no query in state
  });

  it("fetches from history when there is no router state", () => {
    mockLocation.mockReturnValue({ key: "k3", state: {} });
    mockUseSessionHistory.mockReturnValue(
      historyReturn({
        data: {
          message: {
            content: "from history",
            metadata: {
              trace: [{ step: "h" }],
              tier: 3,
              queryUsed: "q",
              guardrailBlocked: true,
              metadata: { a: 1 },
            },
          },
          userQuery: "hist question",
        },
      }),
    );

    const { result } = renderHook(() => useTraceData());

    // needsFetch → real sessionId/requestId passed through
    expect(mockUseSessionHistory).toHaveBeenCalledWith("s1", "r1");
    expect(result.current.data?.content).toBe("from history");
    expect(result.current.data?.tier).toBe(3);
    expect(result.current.data?.guardrailBlocked).toBe(true);
    expect(result.current.data?.userQuery).toBe("hist question");
  });

  it("uses metadata.query as the userQuery fallback when history userQuery is the placeholder", () => {
    mockLocation.mockReturnValue({ key: "k4", state: {} });
    mockUseSessionHistory.mockReturnValue(
      historyReturn({
        data: {
          message: { content: "c", metadata: { query: "meta query" } },
          userQuery: "—",
        },
      }),
    );
    const { result } = renderHook(() => useTraceData());
    expect(result.current.data?.userQuery).toBe("meta query");
    // defaults applied
    expect(result.current.data?.tier).toBe(0);
    expect(result.current.data?.trace).toEqual([]);
  });

  it("returns null data and surfaces loading/error from the history hook", () => {
    mockLocation.mockReturnValue({ key: "k5", state: {} });
    mockUseSessionHistory.mockReturnValue(
      historyReturn({ loading: true, error: "boom" }),
    );
    const { result } = renderHook(() => useTraceData());
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBe("boom");
  });

  it("ignores non-object router state", () => {
    mockLocation.mockReturnValue({ key: "k6", state: "garbage" });
    const { result } = renderHook(() => useTraceData());
    // treated as no state → fetch path
    expect(mockUseSessionHistory).toHaveBeenCalledWith("s1", "r1");
    expect(result.current.data).toBeNull();
  });
});
