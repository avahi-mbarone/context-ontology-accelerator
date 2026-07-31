// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { ChatErrorBoundary } from "./ChatErrorBoundary";

function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("Test render error");
  }
  return <div>Child rendered successfully</div>;
}

describe("ChatErrorBoundary", () => {
  const originalConsoleError = console.error;
  beforeAll(() => {
    console.error = (...args: unknown[]) => {
      const msg = typeof args[0] === "string" ? args[0] : "";
      if (
        msg.includes("ChatErrorBoundary") ||
        msg.includes("The above error occurred") ||
        msg.includes("Error: Uncaught") ||
        msg.includes("Test render error")
      ) {
        return;
      }
      originalConsoleError(...args);
    };
  });

  afterAll(() => {
    console.error = originalConsoleError;
  });

  it("renders children when no error occurs", () => {
    render(
      <ChatErrorBoundary>
        <div>Hello from child</div>
      </ChatErrorBoundary>,
    );
    expect(screen.getByText("Hello from child")).toBeInTheDocument();
  });

  it("shows error fallback when child throws during render", () => {
    render(
      <ChatErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ChatErrorBoundary>,
    );
    expect(
      screen.queryByText("Child rendered successfully"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Failed to render response")).toBeInTheDocument();
  });

  it("does not show retry button when onRetry is not provided", () => {
    render(
      <ChatErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ChatErrorBoundary>,
    );
    expect(screen.queryByText("Retry")).not.toBeInTheDocument();
  });

  it("shows retry button when onRetry is provided", () => {
    render(
      <ChatErrorBoundary onRetry={() => {}}>
        <ThrowingComponent shouldThrow={true} />
      </ChatErrorBoundary>,
    );
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("calls onRetry and resets error state when retry is clicked", () => {
    const onRetry = vi.fn();
    let shouldThrow = true;

    function ConditionalThrower() {
      if (shouldThrow) {
        throw new Error("Test render error");
      }
      return <div>Recovery successful</div>;
    }

    render(
      <ChatErrorBoundary onRetry={onRetry}>
        <ConditionalThrower />
      </ChatErrorBoundary>,
    );

    expect(screen.getByText("Failed to render response")).toBeInTheDocument();

    shouldThrow = false;
    fireEvent.click(screen.getByText("Retry"));

    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.getByText("Recovery successful")).toBeInTheDocument();
  });

  it("does not affect sibling error boundaries (isolation)", () => {
    render(
      <div>
        <ChatErrorBoundary>
          <ThrowingComponent shouldThrow={true} />
        </ChatErrorBoundary>
        <ChatErrorBoundary>
          <ThrowingComponent shouldThrow={false} />
        </ChatErrorBoundary>
      </div>,
    );

    expect(screen.getByText("Failed to render response")).toBeInTheDocument();
    expect(screen.getByText("Child rendered successfully")).toBeInTheDocument();
  });
});
