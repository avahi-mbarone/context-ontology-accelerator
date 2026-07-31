// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  parseCsvList,
  parseColumnDenylist,
  columnDenylistRowsToMap,
  mapToColumnDenylistRows,
} from "../../../src/utils/grant-overrides";

describe("parseCsvList", () => {
  it("parses a simple comma-separated list", () => {
    expect(parseCsvList("a,b,c")).toEqual(["a", "b", "c"]);
  });

  it("trims surrounding whitespace from each item", () => {
    expect(parseCsvList(" a , b ,c ")).toEqual(["a", "b", "c"]);
  });

  it("returns an empty list for an empty string", () => {
    expect(parseCsvList("")).toEqual([]);
  });

  it("returns an empty list for whitespace-only input", () => {
    expect(parseCsvList("   ")).toEqual([]);
  });

  it("filters out blank entries from consecutive commas", () => {
    expect(parseCsvList("a,,b")).toEqual(["a", "b"]);
  });

  it("filters out trailing commas", () => {
    expect(parseCsvList("a,b,")).toEqual(["a", "b"]);
  });

  it("filters out leading commas", () => {
    expect(parseCsvList(",a,b")).toEqual(["a", "b"]);
  });

  it("handles mixed spacing around commas", () => {
    expect(parseCsvList("a, b ,c")).toEqual(["a", "b", "c"]);
  });

  it("preserves a single item without a comma", () => {
    expect(parseCsvList("only")).toEqual(["only"]);
  });

  it("trims a single-item input", () => {
    expect(parseCsvList("  only  ")).toEqual(["only"]);
  });

  it("preserves internal whitespace within an item", () => {
    expect(parseCsvList("a b, c d")).toEqual(["a b", "c d"]);
  });

  it("handles only whitespace and commas as empty", () => {
    expect(parseCsvList(" , , , ")).toEqual([]);
  });
});

describe("parseColumnDenylist", () => {
  it("parses a single line with one column", () => {
    expect(parseColumnDenylist("customers: ssn")).toEqual({
      customers: ["ssn"],
    });
  });

  it("parses a single line with multiple columns", () => {
    expect(parseColumnDenylist("customers: ssn, dob, email")).toEqual({
      customers: ["ssn", "dob", "email"],
    });
  });

  it("parses multiple table lines", () => {
    const text = "customers: ssn\norders: internal_notes";
    expect(parseColumnDenylist(text)).toEqual({
      customers: ["ssn"],
      orders: ["internal_notes"],
    });
  });

  it("returns an empty object for an empty string", () => {
    expect(parseColumnDenylist("")).toEqual({});
  });

  it("ignores lines without a colon", () => {
    const text = "customers: ssn\njust some text\norders: foo";
    expect(parseColumnDenylist(text)).toEqual({
      customers: ["ssn"],
      orders: ["foo"],
    });
  });

  it("ignores lines whose column list is empty", () => {
    expect(parseColumnDenylist("customers:")).toEqual({});
  });

  it("ignores lines whose column list is whitespace only", () => {
    expect(parseColumnDenylist("customers:   ")).toEqual({});
  });

  it("ignores lines with an empty table name", () => {
    expect(parseColumnDenylist(": ssn")).toEqual({});
  });

  it("trims whitespace around the table name", () => {
    expect(parseColumnDenylist("  customers  : ssn")).toEqual({
      customers: ["ssn"],
    });
  });

  it("handles whitespace variations around the colon and columns", () => {
    expect(parseColumnDenylist("customers :  ssn ,  dob")).toEqual({
      customers: ["ssn", "dob"],
    });
  });

  it("ignores blank lines", () => {
    const text = "customers: ssn\n\norders: foo\n";
    expect(parseColumnDenylist(text)).toEqual({
      customers: ["ssn"],
      orders: ["foo"],
    });
  });

  it("handles last-write-wins on duplicate table names", () => {
    const text = "customers: ssn\ncustomers: dob, email";
    expect(parseColumnDenylist(text)).toEqual({
      customers: ["dob", "email"],
    });
  });

  it("only the first colon separates table from columns", () => {
    // A subsequent colon is preserved as part of the column-list segment;
    // when split on commas it becomes a single column with a colon in it.
    expect(parseColumnDenylist("schema:table: col1, col2")).toEqual({
      schema: ["table: col1", "col2"],
    });
  });

  it("filters out empty columns within a line", () => {
    expect(parseColumnDenylist("customers: ssn,, dob,")).toEqual({
      customers: ["ssn", "dob"],
    });
  });

  it("ignores a line that's all whitespace and colons", () => {
    expect(parseColumnDenylist("   :   ")).toEqual({});
  });
});

describe("columnDenylistRowsToMap", () => {
  it("converts rows into a wire map", () => {
    expect(
      columnDenylistRowsToMap([
        { table: "customers", columns: ["ssn", "credit_card"] },
        { table: "orders", columns: ["internal_cost"] },
      ]),
    ).toEqual({
      customers: ["ssn", "credit_card"],
      orders: ["internal_cost"],
    });
  });

  it("trims table names and columns", () => {
    expect(
      columnDenylistRowsToMap([
        { table: "  customers  ", columns: [" ssn ", " credit_card "] },
      ]),
    ).toEqual({ customers: ["ssn", "credit_card"] });
  });

  it("drops rows with a blank table name", () => {
    expect(
      columnDenylistRowsToMap([{ table: "  ", columns: ["ssn"] }]),
    ).toEqual({});
  });

  it("drops rows with no non-empty columns", () => {
    expect(
      columnDenylistRowsToMap([{ table: "customers", columns: ["", "  "] }]),
    ).toEqual({});
  });

  it("de-duplicates columns within a row", () => {
    expect(
      columnDenylistRowsToMap([
        { table: "customers", columns: ["ssn", "ssn", "credit_card"] },
      ]),
    ).toEqual({ customers: ["ssn", "credit_card"] });
  });

  it("last write wins for duplicate table names", () => {
    expect(
      columnDenylistRowsToMap([
        { table: "customers", columns: ["ssn"] },
        { table: "customers", columns: ["credit_card"] },
      ]),
    ).toEqual({ customers: ["credit_card"] });
  });
});

describe("mapToColumnDenylistRows", () => {
  it("converts a wire map into editor rows", () => {
    expect(
      mapToColumnDenylistRows({
        customers: ["ssn", "credit_card"],
        orders: ["internal_cost"],
      }),
    ).toEqual([
      { table: "customers", columns: ["ssn", "credit_card"] },
      { table: "orders", columns: ["internal_cost"] },
    ]);
  });

  it("returns an empty array for undefined", () => {
    expect(mapToColumnDenylistRows(undefined)).toEqual([]);
  });

  it("round-trips with columnDenylistRowsToMap", () => {
    const map = { customers: ["ssn"], orders: ["internal_cost"] };
    expect(columnDenylistRowsToMap(mapToColumnDenylistRows(map))).toEqual(map);
  });
});
