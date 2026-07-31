// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ColumnDenylistEditor } from "./ColumnDenylistEditor";

describe("ColumnDenylistEditor", () => {
  it("shows the empty message when there are no rows", () => {
    render(<ColumnDenylistEditor value={[]} onChange={vi.fn()} />);
    expect(screen.getByText(/no column restrictions/i)).toBeInTheDocument();
  });

  it("adds an empty row when the add button is clicked", () => {
    const onChange = vi.fn();
    render(<ColumnDenylistEditor value={[]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /add table/i }));
    expect(onChange).toHaveBeenCalledWith([{ table: "", columns: [] }]);
  });

  it("renders existing rows with their table name and column chips", () => {
    render(
      <ColumnDenylistEditor
        value={[{ table: "customers", columns: ["ssn", "credit_card"] }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByDisplayValue("customers")).toBeInTheDocument();
    expect(screen.getByText("ssn")).toBeInTheDocument();
    expect(screen.getByText("credit_card")).toBeInTheDocument();
  });

  it("updates the table name for a row", () => {
    const onChange = vi.fn();
    render(
      <ColumnDenylistEditor
        value={[{ table: "", columns: [] }]}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Table name for row 1"), {
      target: { value: "orders" },
    });
    expect(onChange).toHaveBeenCalledWith([{ table: "orders", columns: [] }]);
  });

  it("removes a row when its remove button is clicked", () => {
    const onChange = vi.fn();
    render(
      <ColumnDenylistEditor
        value={[
          { table: "customers", columns: ["ssn"] },
          { table: "orders", columns: ["total"] },
        ]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]!);
    expect(onChange).toHaveBeenCalledWith([
      { table: "orders", columns: ["total"] },
    ]);
  });
});
