// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TokenInput } from "./TokenInput";

describe("TokenInput", () => {
  it("renders existing values as chips", () => {
    render(<TokenInput value={["orders", "customers"]} onChange={vi.fn()} />);
    expect(screen.getByText("orders")).toBeInTheDocument();
    expect(screen.getByText("customers")).toBeInTheDocument();
  });

  it("adds a value when the add button is clicked", () => {
    const onChange = vi.fn();
    render(
      <TokenInput value={[]} onChange={onChange} ariaLabel="Table allowlist" />,
    );
    fireEvent.change(screen.getByLabelText("Table allowlist"), {
      target: { value: "orders" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    expect(onChange).toHaveBeenCalledWith(["orders"]);
  });

  it("adds a value when Enter is pressed", () => {
    const onChange = vi.fn();
    render(
      <TokenInput value={["orders"]} onChange={onChange} ariaLabel="Tables" />,
    );
    const input = screen.getByLabelText("Tables");
    fireEvent.change(input, { target: { value: "products" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["orders", "products"]);
  });

  it("trims whitespace before adding", () => {
    const onChange = vi.fn();
    render(<TokenInput value={[]} onChange={onChange} ariaLabel="Tables" />);
    fireEvent.change(screen.getByLabelText("Tables"), {
      target: { value: "  orders  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    expect(onChange).toHaveBeenCalledWith(["orders"]);
  });

  it("ignores duplicate values", () => {
    const onChange = vi.fn();
    render(
      <TokenInput value={["orders"]} onChange={onChange} ariaLabel="Tables" />,
    );
    fireEvent.change(screen.getByLabelText("Tables"), {
      target: { value: "orders" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not add a blank value", () => {
    const onChange = vi.fn();
    render(<TokenInput value={[]} onChange={onChange} ariaLabel="Tables" />);
    fireEvent.change(screen.getByLabelText("Tables"), {
      target: { value: "   " },
    });
    // Add button is disabled for blank input; Enter is a no-op.
    fireEvent.keyDown(screen.getByLabelText("Tables"), { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a value when its chip is dismissed", () => {
    const onChange = vi.fn();
    render(
      <TokenInput
        value={["orders", "customers"]}
        onChange={onChange}
        ariaLabel="Tables"
      />,
    );
    fireEvent.click(screen.getByLabelText("Remove orders"));
    expect(onChange).toHaveBeenCalledWith(["customers"]);
  });

  it("rejects a value that fails validation and shows the error", () => {
    const onChange = vi.fn();
    render(
      <TokenInput
        value={[]}
        onChange={onChange}
        ariaLabel="Tables"
        validate={(c) => (c.includes(" ") ? "No spaces allowed" : null)}
      />,
    );
    fireEvent.change(screen.getByLabelText("Tables"), {
      target: { value: "bad name" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("No spaces allowed")).toBeInTheDocument();
  });
});
