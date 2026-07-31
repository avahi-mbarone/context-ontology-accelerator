#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate comparison reports from benchmark results.

Usage:
    python3 benchmark/report.py                     # latest result
    python3 benchmark/report.py --compare-tag "strategy-*"   # compare strategy runs
    python3 benchmark/report.py --all               # compare all results
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def load_results(pattern: str | None = None) -> list[tuple]:
    """Load result files matching pattern, sorted by timestamp."""
    files = sorted(RESULTS_DIR.glob("*.json"))
    if pattern:
        files = [f for f in files if fnmatch.fnmatch(f.stem, f"*{pattern}*") or fnmatch.fnmatch(f.stem, pattern)]
    if not files:
        return []
    return [(f, json.loads(f.read_text())) for f in files]


def format_table(rows: list[dict], columns: list[tuple[str, str, int]]) -> str:
    """Format rows as a simple text table."""
    header = " │ ".join(h.ljust(w) for h, _, w in columns)
    sep = "─┼─".join("─" * w for _, _, w in columns)
    lines = [header, sep]
    for row in rows:
        line = " │ ".join(str(row.get(k, ""))[:w].ljust(w) for _, k, w in columns)
        lines.append(line)
    return "\n".join(lines)


def summarize_one(data: dict) -> dict:
    """Extract summary metrics from a result file."""
    meta = data.get("metadata", {})
    summary = data.get("summary", {})
    results = data.get("results", [])

    total = summary.get("total", len(results))
    executed = summary.get("executed", 0)
    errors = summary.get("errors", 0)
    avg_latency = summary.get("avg_latency_ms", 0)
    accuracy_pct = summary.get("accuracy_pct")

    # Compute avg confidence from results
    confidences = [r["confidence"] for r in results if r.get("confidence") is not None]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    # Category breakdown
    cat_exec = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in cat_exec:
            cat_exec[cat] = {"total": 0, "executed": 0, "accurate": 0}
        cat_exec[cat]["total"] += 1
        if r.get("executed"):
            cat_exec[cat]["executed"] += 1
        if r.get("accurate") is True:
            cat_exec[cat]["accurate"] += 1

    agg = cat_exec.get("aggregation", {"total": 0, "executed": 0, "accurate": 0})
    non_agg = cat_exec.get("non-aggregation", {"total": 0, "executed": 0, "accurate": 0})

    def _cat_pct(stats: dict) -> str:
        """Format category accuracy/execution percentage."""
        if not stats["total"]:
            return "-"
        if accuracy_pct is not None:
            return f"{100 * stats['accurate'] / stats['total']:.0f}%"
        return f"{100 * stats['executed'] / stats['total']:.0f}%x"

    agg_pct = _cat_pct(agg)
    nonagg_pct = _cat_pct(non_agg)

    return {
        "strategy": meta.get("strategy") or "default",
        "model": (meta.get("model") or "default").split(".")[-1][:25],
        "total": total,
        "exec_pct": f"{100 * executed / total:.0f}%" if total else "0%",
        "acc_pct": f"{accuracy_pct:.1f}%" if accuracy_pct is not None else "-",
        "err_pct": f"{100 * errors / total:.0f}%" if total else "0%",
        "avg_ms": f"{avg_latency:.0f}",
        "avg_conf": f"{avg_conf:.2f}",
        "agg_acc": agg_pct,
        "nonagg_acc": nonagg_pct,
        "timestamp": meta.get("timestamp", "")[:16],
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark Report Generator")
    parser.add_argument("--compare-tag", default=None, help="Glob pattern to filter result files")
    parser.add_argument("--all", action="store_true", help="Compare all results")
    parser.add_argument("--latest", action="store_true", help="Show only latest result (default if no flags)")
    args = parser.parse_args()

    pattern = args.compare_tag
    if args.all:
        pattern = "*"

    loaded = load_results(pattern)
    if not loaded:
        if not args.all and not pattern:
            loaded = load_results("*")
            if loaded:
                loaded = [loaded[-1]]
        if not loaded:
            print("No results found in", RESULTS_DIR)
            sys.exit(1)

    summaries = [summarize_one(data) for _, data in loaded]

    columns = [
        ("Strategy", "strategy", 18),
        ("Model", "model", 25),
        ("N", "total", 5),
        ("Exec%", "exec_pct", 6),
        ("Acc%", "acc_pct", 6),
        ("Err%", "err_pct", 5),
        ("AvgMs", "avg_ms", 6),
        ("Conf", "avg_conf", 5),
        ("Agg", "agg_acc", 8),
        ("NonAgg", "nonagg_acc", 8),
    ]

    print("\n" + "═" * 78)
    print("  BENCHMARK COMPARISON")
    print("═" * 78)
    print()
    print(format_table(summaries, columns))
    print()

    if len(summaries) > 1:
        # Highlight best
        def _pct_val(s, key):
            v = s.get(key, "0%")
            try:
                return float(v.rstrip("%"))
            except (ValueError, AttributeError):
                return 0.0

        best_acc = max(summaries, key=lambda s: _pct_val(s, "acc_pct"))
        if _pct_val(best_acc, "acc_pct") > 0:
            print(f"  Best accuracy:  {best_acc['strategy']}/{best_acc['model']} ({best_acc['acc_pct']})")
        best_exec = max(summaries, key=lambda s: _pct_val(s, "exec_pct"))
        print(f"  Best execution: {best_exec['strategy']}/{best_exec['model']} ({best_exec['exec_pct']})")
        fastest = min(summaries, key=lambda s: int(s["avg_ms"]))
        print(f"  Fastest:        {fastest['strategy']}/{fastest['model']} ({fastest['avg_ms']}ms avg)")
    print()


if __name__ == "__main__":
    main()
