# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared connector filter compilation.

`filters.py` is the single source of truth both the JDBC and Glue connectors use
to interpret schema/table filters, so it's tested directly here (independent of
either connector) to pin the contract and stop the two from drifting.
"""

from __future__ import annotations

from coa_sources.database.connectors.filters import compile_filter, split_glob_list


class TestSplitGlobList:
    def test_single_glob_no_delimiter(self):
        assert split_glob_list("orders") == ["orders"]

    def test_pipe_delimited(self):
        assert split_glob_list("orders|customers") == ["orders", "customers"]

    def test_comma_delimited(self):
        assert split_glob_list("constructor*,results") == ["constructor*", "results"]

    def test_mixed_delimiters_and_whitespace_trimmed(self):
        assert split_glob_list(" a | b , c ") == ["a", "b", "c"]

    def test_empty_entries_dropped(self):
        assert split_glob_list("a||,b,") == ["a", "b"]

    def test_delimiter_inside_char_class_not_split(self):
        # A comma inside [...] is part of the glob, not a list separator.
        assert split_glob_list("log_[a,b]") == ["log_[a,b]"]
        assert split_glob_list("log_[a,b]|temp_*") == ["log_[a,b]", "temp_*"]


class TestCompileFilter:
    def test_none_pattern_returns_none(self):
        assert compile_filter(None, "table_filter") is None

    def test_empty_pattern_returns_none(self):
        assert compile_filter("", "table_filter") is None
        assert compile_filter("  |  ", "table_filter") is None

    def test_single_glob_matches_and_rejects(self):
        rx = compile_filter("orders", "table_filter")
        assert rx is not None
        assert rx.match("orders")
        assert not rx.match("customers")

    def test_pipe_list_matches_any(self):
        rx = compile_filter("orders|customers", "table_filter")
        assert rx.match("orders")
        assert rx.match("customers")
        assert not rx.match("products")

    def test_comma_list_with_star_glob(self):
        rx = compile_filter("constructor*,results", "table_filter")
        assert rx.match("constructor_standings")
        assert rx.match("results")
        assert not rx.match("drivers")

    def test_star_matches_prefix_not_substring(self):
        rx = compile_filter("staging_*", "table_exclude_filter")
        assert rx.match("staging_users")
        # fnmatch globs are full-match, so a non-prefix does not match.
        assert not rx.match("my_staging_users")

    def test_bracket_char_class_preserved(self):
        rx = compile_filter("log_[0-9]", "table_filter")
        assert rx.match("log_1")
        assert not rx.match("log_a")

    def test_unbalanced_bracket_falls_back_to_literal(self):
        # fnmatch.translate escapes an unclosed "[" into a literal, so it never
        # raises — the pattern matches the literal name rather than erroring.
        # (This is why compile_filter's `except re.error` guard is effectively
        # unreachable through fnmatch output.)
        rx = compile_filter("orders[", "table_filter")
        assert rx is not None
        assert rx.match("orders[")
        assert not rx.match("orders")
