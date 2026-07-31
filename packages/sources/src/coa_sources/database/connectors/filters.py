# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared schema/table filter compilation for database connectors.

The source-creation UI labels filter fields "regex" with an ``orders|customers``
placeholder, so users type pipe/comma-delimited lists of shell globs. Both the
JDBC connector (client-side schema/table filtering) and the Glue connector
(client-side ``table_exclude_filter``) must interpret them identically —
treating the whole string as a single ``fnmatch`` glob silently matches nothing
for a delimited list. This module is the single source of truth so the two
connectors cannot drift apart.
"""

from __future__ import annotations

import fnmatch
import re


def split_glob_list(pattern: str) -> list[str]:
    """Split a filter into its individual globs on top-level ``|`` / ``,``.

    Delimiters inside a glob character class (``[...]``) are NOT split on, so
    a class such as ``log_[a,b]`` stays a single glob. (Table/schema
    identifiers can't contain ``|``/``,``, so the only place a delimiter is
    meaningful mid-glob is inside a bracket expression.) Surrounding
    whitespace on each entry is trimmed; empty entries are dropped.
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0  # inside a [...] character class
    for ch in pattern:
        if ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch in "|," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def compile_filter(pattern: str | None, field_name: str) -> re.Pattern[str] | None:
    """Compile an optional filter to a full-match regex; return None if no pattern.

    The filter is a list of one or more shell globs (``*``, ``?``, ``[seq]``)
    separated by ``|`` or ``,`` — e.g. ``circuits|drivers|races`` or
    ``constructor*,results``. A name matches the filter if it matches ANY of the
    globs. A single glob (no delimiter) behaves exactly as a plain glob.

    Comma/pipe support is deliberate: the source-creation UI labels this field
    "regex" with an ``orders|customers`` placeholder, so users reasonably type
    pipe-delimited lists. Treating the whole string as one glob silently matched
    nothing (``orders|customers`` is not a valid glob token). Delimiters inside a
    glob character class (``[a,b]``) are preserved — see ``split_glob_list``.
    """
    if not pattern:
        return None
    globs = split_glob_list(pattern)
    if not globs:
        return None
    try:
        # OR the per-glob translations together. fnmatch.translate wraps each in
        # ``(?s:...)\Z``; alternating those gives a full-match-any.
        return re.compile("|".join(fnmatch.translate(g) for g in globs))
    except re.error as exc:
        raise ValueError(f"Invalid pattern for {field_name}: {exc}") from exc
