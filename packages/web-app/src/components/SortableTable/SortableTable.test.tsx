// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { SortableTable } from "./SortableTable";

interface Row {
  id: string;
  label: string;
  count: number;
}

const ROWS: Row[] = [
  { id: "a", label: "Bravo", count: 3 },
  { id: "b", label: "Alpha", count: 1 },
  { id: "c", label: "Charlie", count: 2 },
];

function rowLabels(): string[] {
  // Cloudscape renders each row-header cell; read them in DOM order.
  return screen
    .getAllByRole("rowheader")
    .map((el) => el.textContent?.trim() ?? "");
}

describe("SortableTable sorting", () => {
  it("reorders rows when a comparator column header is clicked (with selection)", () => {
    render(
      <SortableTable<Row>
        items={ROWS}
        trackBy="id"
        selectionType="single"
        selectedItems={[]}
        onSelectionChange={() => {}}
        columnDefinitions={[
          {
            id: "label",
            header: "Label",
            isRowHeader: true,
            sortingField: "label",
            cell: (r) => r.label,
          },
          {
            id: "count",
            header: "Count",
            sortingComparator: (a, b) => a.count - b.count,
            cell: (r) => r.count,
          },
        ]}
      />,
    );

    // Click the "Count" column header to sort ascending by count.
    const countHeader = screen.getByRole("columnheader", { name: /count/i });
    const btn = within(countHeader).getByRole("button");
    fireEvent.click(btn);

    // Ascending by count => Alpha(1), Charlie(2), Bravo(3)
    expect(rowLabels()).toEqual(["Alpha", "Charlie", "Bravo"]);
  });

  it("reorders with onRowClick + a seeded default sort (Proposed Classes shape)", () => {
    render(
      <SortableTable<Row>
        items={ROWS}
        trackBy="id"
        defaultSortingColumnId="label"
        selectionType="single"
        selectedItems={[]}
        onSelectionChange={() => {}}
        onRowClick={() => {}}
        columnDefinitions={[
          {
            id: "label",
            header: "Label",
            isRowHeader: true,
            sortingField: "label",
            cell: (r) => r.label,
          },
          {
            id: "count",
            header: "Count",
            sortingComparator: (a, b) => a.count - b.count,
            cell: (r) => r.count,
          },
        ]}
      />,
    );
    // Seeded default = label asc => Alpha, Bravo, Charlie
    expect(rowLabels()).toEqual(["Alpha", "Bravo", "Charlie"]);
    // Click Count header => 1,2,3 => Alpha, Charlie, Bravo
    fireEvent.click(
      within(screen.getByRole("columnheader", { name: /count/i })).getByRole(
        "button",
      ),
    );
    expect(rowLabels()).toEqual(["Alpha", "Charlie", "Bravo"]);
  });

  it("reorders when items is a NEW array reference each render (Grounding shape)", () => {
    // Grounding passes items={[...candidates].sort(...)} — a fresh array every
    // render. Simulate by re-rendering with a new array of the same content.
    const { rerender } = render(
      <SortableTable<Row>
        items={[...ROWS]}
        trackBy="id"
        defaultSortingColumnId="count"
        defaultSortingDescending
        selectionType="single"
        selectedItems={[]}
        onSelectionChange={() => {}}
        columnDefinitions={[
          {
            id: "label",
            header: "Label",
            isRowHeader: true,
            sortingComparator: (a, b) => a.label.localeCompare(b.label),
            cell: (r) => r.label,
          },
          {
            id: "count",
            header: "Count",
            sortingComparator: (a, b) => a.count - b.count,
            cell: (r) => r.count,
          },
        ]}
      />,
    );
    // Seeded default = count desc => Bravo(3), Charlie(2), Alpha(1)
    expect(rowLabels()).toEqual(["Bravo", "Charlie", "Alpha"]);
    // Click Label header to sort asc by label => Alpha, Bravo, Charlie
    fireEvent.click(
      within(screen.getByRole("columnheader", { name: /label/i })).getByRole(
        "button",
      ),
    );
    expect(rowLabels()).toEqual(["Alpha", "Bravo", "Charlie"]);
    // Force a parent re-render with a brand-new items array + NEW inline
    // comparator instances (the real-world break: new function refs each render).
    rerender(
      <SortableTable<Row>
        items={[...ROWS]}
        trackBy="id"
        defaultSortingColumnId="count"
        defaultSortingDescending
        selectionType="single"
        selectedItems={[]}
        onSelectionChange={() => {}}
        columnDefinitions={[
          {
            id: "label",
            header: "Label",
            isRowHeader: true,
            sortingComparator: (a, b) => a.label.localeCompare(b.label),
            cell: (r) => r.label,
          },
          {
            id: "count",
            header: "Count",
            sortingComparator: (a, b) => a.count - b.count,
            cell: (r) => r.count,
          },
        ]}
      />,
    );
    // Sort should persist across the re-render: label asc => Alpha, Bravo, Charlie
    expect(rowLabels()).toEqual(["Alpha", "Bravo", "Charlie"]);
  });
});
