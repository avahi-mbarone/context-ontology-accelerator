// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen, fireEvent } from "@testing-library/react";
import { ChatInput } from "./ChatInput";

describe("ChatInput", () => {
  const defaultProps = {
    value: "",
    onChange: vi.fn(),
    onSubmit: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders an input with placeholder", () => {
    render(<ChatInput {...defaultProps} />);
    expect(screen.getByRole("textbox", { name: "Query" })).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(
        "Ask a question against the governed surface...",
      ),
    ).toBeInTheDocument();
  });

  it("renders a submit button", () => {
    render(<ChatInput {...defaultProps} />);
    expect(
      screen.getByRole("button", { name: "Run query" }),
    ).toBeInTheDocument();
  });

  it("disables input when disabled prop is true", () => {
    render(<ChatInput {...defaultProps} disabled />);
    expect(screen.getByRole("textbox", { name: "Query" })).toBeDisabled();
  });

  it("disables submit button when submitDisabled is true", () => {
    render(<ChatInput {...defaultProps} submitDisabled />);
    expect(screen.getByRole("button", { name: "Run query" })).toBeDisabled();
  });

  it("calls onSubmit when submit button is clicked", () => {
    render(<ChatInput {...defaultProps} value="test" />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(defaultProps.onSubmit).toHaveBeenCalledTimes(1);
  });

  it("accepts a custom placeholder", () => {
    render(<ChatInput {...defaultProps} placeholder="Custom placeholder" />);
    expect(
      screen.getByPlaceholderText("Custom placeholder"),
    ).toBeInTheDocument();
  });
});
