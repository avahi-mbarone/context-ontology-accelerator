// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useImportOsiFile, useExportOsi } from "./use-metrics";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockPost = vi.fn();
const mockGet = vi.fn();

vi.mock("@components/ApiClientProvider", () => ({
  useApiClient: () => ({
    post: mockPost,
    get: mockGet,
    put: vi.fn(),
    del: vi.fn(),
  }),
}));

const NS_ID = "550e8400-e29b-41d4-a716-446655440000";

function makeHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
  return { wrapper, queryClient };
}

function makeFile(content: string, size?: number): File {
  const file = new File([content], "metrics.yaml", {
    type: "application/x-yaml",
  });
  // jsdom doesn't implement Blob.text(); stub it so the inline path is deterministic.
  vi.spyOn(file, "text").mockResolvedValue(content);
  if (size !== undefined) {
    Object.defineProperty(file, "size", { value: size });
  }
  return file;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useImportOsiFile", () => {
  beforeEach(() => {
    mockPost.mockReset();
    vi.unstubAllGlobals();
  });

  it("uses the inline content path for small files (no cross-origin S3 PUT)", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    mockPost.mockResolvedValueOnce({
      status: "COMPLETED",
      metricsCreated: 2,
      metricsUpdated: 0,
      datasetsResolved: 0,
    });

    const { wrapper } = makeHarness();
    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });

    await result.current.mutateAsync(
      makeFile('osi_spec_version: "1.0"\nmetrics: []\n'),
    );

    expect(mockPost).toHaveBeenCalledTimes(1);
    expect(mockPost).toHaveBeenCalledWith(
      `/namespaces/${NS_ID}/import-osi`,
      expect.objectContaining({
        content: expect.stringContaining("osi_spec_version"),
      }),
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("falls back to the pre-signed S3 upload flow for large files", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchSpy);
    mockPost
      .mockResolvedValueOnce({
        uploadUrl: "https://s3.example/put",
        s3Key: "ns/imports/x/metrics.yaml",
      })
      .mockResolvedValueOnce({
        status: "COMPLETED",
        metricsCreated: 99,
        metricsUpdated: 0,
        datasetsResolved: 1,
      });

    const { wrapper } = makeHarness();
    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });

    await result.current.mutateAsync(makeFile("x", 6 * 1024 * 1024)); // > 5 MB

    expect(mockPost).toHaveBeenNthCalledWith(
      1,
      `/namespaces/${NS_ID}/import-osi/upload-url`,
      expect.objectContaining({ filename: "metrics.yaml" }),
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "https://s3.example/put",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(mockPost).toHaveBeenNthCalledWith(
      2,
      `/namespaces/${NS_ID}/import-osi`,
      {
        s3Key: "ns/imports/x/metrics.yaml",
      },
    );
  });

  it("invalidates the metrics cache on a COMPLETED import", async () => {
    vi.stubGlobal("fetch", vi.fn());
    mockPost.mockResolvedValueOnce({
      status: "COMPLETED",
      metricsCreated: 1,
      metricsUpdated: 0,
      datasetsResolved: 0,
    });
    const { wrapper, queryClient } = makeHarness();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });
    await result.current.mutateAsync(makeFile("metrics: []\n"));

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["metrics", NS_ID],
    });
  });

  it("does NOT invalidate the cache when the import is not COMPLETED", async () => {
    vi.stubGlobal("fetch", vi.fn());
    mockPost.mockResolvedValueOnce({
      status: "IN_PROGRESS",
      jobId: "job-1",
      metricsCreated: 0,
      metricsUpdated: 0,
      datasetsResolved: 0,
    });
    const { wrapper, queryClient } = makeHarness();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });
    await result.current.mutateAsync(makeFile("metrics: []\n"));

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("rejects when the inline import POST fails", async () => {
    vi.stubGlobal("fetch", vi.fn());
    mockPost.mockRejectedValueOnce(
      new Error("API POST /import-osi failed (400): bad"),
    );
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });
    await expect(
      result.current.mutateAsync(makeFile("metrics: []\n")),
    ).rejects.toThrow(/400/);
  });

  it("rejects with a clear message when reading the file fails", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const file = new File(["x"], "metrics.yaml", {
      type: "application/x-yaml",
    });
    Object.defineProperty(file, "size", { value: 10 });
    vi.spyOn(file, "text").mockRejectedValue(new Error("read boom"));
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });
    await expect(result.current.mutateAsync(file)).rejects.toThrow(
      /Failed to read file: read boom/,
    );
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("rejects when the upload-url request fails (large file)", async () => {
    vi.stubGlobal("fetch", vi.fn());
    mockPost.mockRejectedValueOnce(new Error("upload-url failed"));
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });
    await expect(
      result.current.mutateAsync(makeFile("x", 6 * 1024 * 1024)),
    ).rejects.toThrow(/upload-url failed/);
  });

  it("rejects when the large-file S3 upload fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 403 }),
    );
    mockPost.mockResolvedValueOnce({
      uploadUrl: "https://s3.example/put",
      s3Key: "k",
    });
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });
    await expect(
      result.current.mutateAsync(makeFile("x", 6 * 1024 * 1024)),
    ).rejects.toThrow(/S3 upload failed: 403/);
  });

  it("rejects when the final import POST fails after a successful S3 upload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200 }),
    );
    mockPost
      .mockResolvedValueOnce({
        uploadUrl: "https://s3.example/put",
        s3Key: "k",
      })
      .mockRejectedValueOnce(new Error("import-osi failed (503)"));
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useImportOsiFile(NS_ID), { wrapper });
    await expect(
      result.current.mutateAsync(makeFile("x", 6 * 1024 * 1024)),
    ).rejects.toThrow(/import-osi failed/);
  });
});

describe("useExportOsi", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("calls export-osi with no query string when exporting the full namespace", async () => {
    mockGet.mockResolvedValueOnce({ content: 'osi_spec_version: "1.0"\n' });
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useExportOsi(NS_ID), { wrapper });
    await result.current.mutateAsync();

    expect(mockGet).toHaveBeenCalledWith(`/namespaces/${NS_ID}/export-osi`);
  });

  it("appends a repeated `names` query param for a scoped export", async () => {
    mockGet.mockResolvedValueOnce({ content: 'osi_spec_version: "1.0"\n' });
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useExportOsi(NS_ID), { wrapper });
    await result.current.mutateAsync({ names: ["metric_a", "metric_b"] });

    expect(mockGet).toHaveBeenCalledWith(
      `/namespaces/${NS_ID}/export-osi?names=metric_a&names=metric_b`,
    );
  });

  it("treats an empty names array the same as exporting everything", async () => {
    mockGet.mockResolvedValueOnce({ content: 'osi_spec_version: "1.0"\n' });
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useExportOsi(NS_ID), { wrapper });
    await result.current.mutateAsync({ names: [] });

    expect(mockGet).toHaveBeenCalledWith(`/namespaces/${NS_ID}/export-osi`);
  });

  it("rejects when the export request fails", async () => {
    mockGet.mockRejectedValueOnce(new Error("export-osi failed (500)"));
    const { wrapper } = makeHarness();

    const { result } = renderHook(() => useExportOsi(NS_ID), { wrapper });
    await expect(result.current.mutateAsync()).rejects.toThrow(/500/);
  });
});
