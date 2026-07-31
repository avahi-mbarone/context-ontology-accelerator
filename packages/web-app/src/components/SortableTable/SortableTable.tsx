// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * SortableTable — a thin wrapper over Cloudscape ``<Table>`` that adds
 * client-side column sorting.
 *
 * Drop-in replacement for ``<Table>``: pass the same ``items`` and
 * ``columnDefinitions``. Any column whose definition declares a
 * ``sortingField`` (direct property) or ``sortingComparator`` (computed cell,
 * e.g. an array length or a derived badge) becomes click-to-sort in the header;
 * columns with neither stay unsortable. Clicking cycles ascending → descending.
 *
 * Why not ``useCollection``: Cloudscape tracks the active sort by the
 * ``sortingComparator`` FUNCTION INSTANCE. Our callers declare column
 * definitions inline in JSX, so a new comparator instance is created on every
 * render — ``useCollection`` (and a raw controlled ``<Table>``) then "loses"
 * the active column and silently stops reordering ("clickable but rows don't
 * reorder"). This wrapper instead tracks the active column by its stable
 * ``id`` string and performs the sort itself, re-resolving the comparator from
 * the CURRENT ``columnDefinitions`` each render — so new comparator instances
 * and new ``items`` array references can't break sorting.
 *
 * ``defaultSortingColumnId`` seeds the initial sort by column ``id``;
 * ``defaultSortingDescending`` seeds the initial direction. All other
 * ``<Table>`` props (selection, ``trackBy``, ``variant``, ``header``, ``empty``,
 * ``loading``, ``onRowClick``, …) pass straight through.
 */
import { useMemo, useState } from "react";
import Table, { type TableProps } from "@cloudscape-design/components/table";

export interface SortableTableProps<T> extends Omit<
  TableProps<T>,
  "sortingColumn" | "sortingDescending" | "onSortingChange"
> {
  /** ``id`` of the column to sort by on first render (default: source order). */
  defaultSortingColumnId?: string;
  /** Whether the initial sort is descending (default false = ascending). */
  defaultSortingDescending?: boolean;
}

/** Type guard: narrows `unknown` to a string-indexable record (no `as` cast). */
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

/**
 * Read a named field off a row via `unknown` narrowing (no type assertion).
 * Cloudscape's ``sortingField`` is a plain string, so we cannot express it as
 * ``keyof T`` without an `as` cast; instead narrow the row with a type guard.
 */
function readField(row: unknown, field: string): unknown {
  return isRecord(row) ? row[field] : undefined;
}

export function SortableTable<T>({
  items,
  columnDefinitions,
  defaultSortingColumnId,
  defaultSortingDescending,
  ...tableProps
}: SortableTableProps<T>): React.JSX.Element {
  // Track the active sort by STABLE id (not by comparator instance).
  const [sortingColumnId, setSortingColumnId] = useState<string | undefined>(
    defaultSortingColumnId,
  );
  const [isDescending, setIsDescending] = useState<boolean>(
    defaultSortingDescending ?? false,
  );

  const columns = columnDefinitions ?? [];
  const activeColumn = sortingColumnId
    ? columns.find((c) => c.id === sortingColumnId)
    : undefined;

  const sortedItems = useMemo(() => {
    const list = items ?? [];
    if (!activeColumn) return list;

    const { sortingComparator, sortingField } = activeColumn;
    if (!sortingComparator && !sortingField) return list;

    const cmp = (a: T, b: T): number => {
      if (sortingComparator) return sortingComparator(a, b);
      // Fall back to comparing the named field generically. Read it through an
      // `unknown` narrowing (no `as` cast — frontend-typescript rule) since a
      // Cloudscape sortingField is a string, not a typed key.
      const av = readField(a, sortingField ?? "");
      const bv = readField(b, sortingField ?? "");
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av ?? "").localeCompare(String(bv ?? ""));
    };

    // Copy before sort — never mutate the caller's array. A caller-provided
    // comparator that throws (e.g. on incomplete/malformed row data) must not
    // crash the render tree; fall back to the unsorted list on error.
    try {
      const out = [...list].sort(cmp);
      return isDescending ? out.reverse() : out;
    } catch (error) {
      console.error(
        "SortableTable: sorting comparator threw; showing unsorted",
        error,
      );
      return list;
    }
  }, [items, activeColumn, isDescending]);

  return (
    <Table
      {...tableProps}
      columnDefinitions={columns}
      items={sortedItems}
      sortingColumn={activeColumn}
      sortingDescending={isDescending}
      onSortingChange={({ detail }) => {
        // detail.sortingColumn is the column-definition object; resolve it back
        // to its stable id by reference identity (SortingColumn has no `id`).
        const clicked = columns.find((c) => c === detail.sortingColumn);
        setSortingColumnId(clicked?.id);
        setIsDescending(detail.isDescending ?? false);
      }}
    />
  );
}
