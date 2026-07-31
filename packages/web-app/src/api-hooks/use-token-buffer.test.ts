// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act } from "@testing-library/react";
import { vi } from "vitest";
import { useTokenBuffer } from "./use-token-buffer";

describe("useTokenBuffer", () => {
  const mockDispatch = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("append accumulates text for a requestId", () => {
    const { result } = renderHook(() => useTokenBuffer(mockDispatch));

    act(() => {
      result.current.append("req-1", "Hello");
      result.current.append("req-1", " World");
    });

    const flushed = result.current.flush("req-1");
    expect(flushed).toBe("Hello World");
  });

  it("flush returns accumulated text and removes it", () => {
    const { result } = renderHook(() => useTokenBuffer(mockDispatch));

    act(() => {
      result.current.append("req-1", "data");
    });

    const first = result.current.flush("req-1");
    expect(first).toBe("data");

    const second = result.current.flush("req-1");
    expect(second).toBeUndefined();
  });

  it("flush returns undefined for unknown requestId", () => {
    const { result } = renderHook(() => useTokenBuffer(mockDispatch));

    const flushed = result.current.flush("nonexistent");
    expect(flushed).toBeUndefined();
  });

  it("clear removes without returning", () => {
    const { result } = renderHook(() => useTokenBuffer(mockDispatch));

    act(() => {
      result.current.append("req-1", "some data");
    });

    act(() => {
      result.current.clear("req-1");
    });

    const flushed = result.current.flush("req-1");
    expect(flushed).toBeUndefined();
  });

  it("multiple requestIds are independent", () => {
    const { result } = renderHook(() => useTokenBuffer(mockDispatch));

    act(() => {
      result.current.append("req-1", "Alpha");
      result.current.append("req-2", "Beta");
      result.current.append("req-1", " more");
    });

    expect(result.current.flush("req-1")).toBe("Alpha more");
    expect(result.current.flush("req-2")).toBe("Beta");
  });

  it("interval dispatches TOKEN actions and clears buffer", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useTokenBuffer(mockDispatch));

    act(() => {
      result.current.append("req-1", "streamed text");
    });

    act(() => {
      vi.advanceTimersByTime(75);
    });

    expect(mockDispatch).toHaveBeenCalledWith({
      type: "TOKEN",
      requestId: "req-1",
      text: "streamed text",
    });

    // Buffer should be cleared after interval fires
    const flushed = result.current.flush("req-1");
    expect(flushed).toBeUndefined();

    vi.useRealTimers();
  });

  it("interval does not dispatch for empty text", () => {
    vi.useFakeTimers();
    renderHook(() => useTokenBuffer(mockDispatch));

    act(() => {
      vi.advanceTimersByTime(75);
    });

    expect(mockDispatch).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
