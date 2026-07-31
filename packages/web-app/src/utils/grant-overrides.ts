// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Parsing helpers for the grant-override form fields used by GetNamespace
 * (table allowlist, column denylist, allowed metrics).
 *
 * These map free-form textarea input into the canonical wire shapes:
 *   tableAllowlist: string[]
 *   columnDenylist: Record<string, string[]>
 *   allowedMetrics: string[]
 *
 * Inputs may contain whitespace, blank entries, or malformed lines — these
 * helpers normalize and discard rather than throwing, so users see only the
 * well-formed entries reflected in the request payload.
 */

/** Parses a comma-separated string into a trimmed, non-empty string list. */
export function parseCsvList(text: string): string[] {
  if (!text) return [];
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Parses a column denylist textarea into a map. One table per line:
 * `table: col1, col2`. Lines without a colon, with an empty table, or with
 * no non-empty columns are ignored. Duplicate table names overwrite earlier
 * entries (last-write-wins).
 *
 * Only the first colon on a line separates the table name from the columns;
 * subsequent colons are preserved as part of the column-list segment (which
 * is then split on commas, so colons within column names pass through).
 */
export function parseColumnDenylist(text: string): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  if (!text) return out;
  for (const line of text.split("\n")) {
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const table = line.slice(0, idx).trim();
    const cols = parseCsvList(line.slice(idx + 1));
    if (table && cols.length) out[table] = cols;
  }
  return out;
}

/**
 * A single editable column-denylist row, as used by the `ColumnDenylistEditor`
 * UI. Kept structurally compatible with the component's `ColumnDenylistRow`.
 */
export interface ColumnDenylistRowValue {
  table: string;
  columns: string[];
}

/**
 * Converts editor rows into the canonical wire map (`Record<string, string[]>`).
 *
 * The table name is trimmed and each column is trimmed; rows with a blank
 * table name or with no non-empty columns are dropped, and duplicate columns
 * within a row are removed (first occurrence wins). Duplicate table names
 * overwrite earlier entries (last-write-wins), matching `parseColumnDenylist`.
 */
export function columnDenylistRowsToMap(
  rows: ColumnDenylistRowValue[],
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const { table, columns } of rows) {
    const trimmedTable = table.trim();
    if (!trimmedTable) continue;
    const cols = Array.from(
      new Set(columns.map((c) => c.trim()).filter(Boolean)),
    );
    if (cols.length) out[trimmedTable] = cols;
  }
  return out;
}

/** Converts a wire denylist map into editor rows for initial form state. */
export function mapToColumnDenylistRows(
  map: Record<string, string[]> | undefined,
): ColumnDenylistRowValue[] {
  if (!map) return [];
  return Object.entries(map).map(([table, columns]) => ({
    table,
    columns: [...columns],
  }));
}
