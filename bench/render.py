"""Render BENCH.md from a results/bench-*.json snapshot (numbers only from JSON)."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

PATH_LABEL = {
    "rows": "rows (classic driver, current)",
    "adbc_rows": "adbc_rows (ADBC driver, current result set)",
    "arrow": "arrow (ADBC + from_arrow, prototype)",
}
DRIVER = {
    ("postgres", "rows"): "psycopg2",
    ("duckdb", "rows"): "duckdb-engine",
    ("flightsql", "rows"): "flightsql-dbapi",
}


def mib(b: float) -> str:
    return f"{b / 2**20:,.0f}"


def s(x: float) -> str:
    if x < 0.001:
        return "<0.001"
    return f"{x:.3f}" if x < 10 else f"{x:.1f}"


def render(snap: dict, title: str = "# Benchmark results") -> str:
    res = snap["results"]
    env = snap["env"]
    lines = [title, ""]
    if res and res[0].get("downstream") == "ipc":
        lines += ["Downstream: **IPC only** (`--downstream ipc`): Superset's `to_pandas_df()` is not run, "
                  "so `pandas` / `total (pandas)` are `-`.", ""]
    lines += [
        f"Snapshot: `{snap.get('_file', '')}` (started {snap['started_utc']}, finished {snap['finished_utc']}).",
        "All numbers below are copied from that JSON by `bench/render.py`; medians over the rounds shown.",
        "",
        "Times in seconds (wall clock). `total (IPC)` = fetch + result set + `write_ipc_buffer` "
        "(SQL Lab with `RESULTS_BACKEND_USE_MSGPACK=True`, the default). `total (pandas)` = fetch + "
        "result set + `to_pandas_df()`. Peak RSS is the resident-memory high-water mark above the RSS "
        "just before the query (VmHWM reset). tracemalloc peak counts Python-heap allocations only "
        "(Arrow/ADBC C buffers are not traced) and comes from a separate run.",
        "",
    ]
    for rows in sorted({r["rows"] for r in res}):
        lines += [f"## {rows:,} rows", ""]
        lines += ["| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for backend in common.BACKENDS:
            base = next((r for r in res if r["rows"] == rows and r["backend"] == backend and r["path"] == "rows"), None)
            for path in common.PATHS:
                r = next((x for x in res if x["rows"] == rows and x["backend"] == backend and x["path"] == path), None)
                if r is None:
                    sk = next((x for x in snap.get("skipped", []) if x["rows"] == rows and x["backend"] == backend and x["path"] == path), None)
                    if sk:
                        lines.append(f"| {backend} | {path} | | | skipped: {sk['reason']} | | | | | | | | |")
                    continue
                drv = DRIVER.get((backend, path), {"postgres": "adbc-driver-postgresql", "duckdb": "adbc_driver_duckdb", "flightsql": "adbc-driver-flightsql"}[backend])
                sp = (f"{base['total_ipc_s']['median'] / r['total_ipc_s']['median']:.1f}x" if base else "n/a (rows path skipped)")
                m = lambda k: "-" if r[k] is None else s(r[k]["median"])  # noqa: E731
                lines.append(
                    f"| {backend} | {path} | {drv} | {r['rounds']} | {m('fetch_s')} | {m('result_set_s')} | {m('ipc_s')} | {m('pandas_s')} | "
                    f"**{m('total_ipc_s')}** | {m('total_pandas_s')} | {sp} | {mib(r['peak_rss_delta_bytes_median'])} | {mib(r['tracemalloc_peak_bytes'])} |"
                )
        lines.append("")
    if snap.get("skipped"):
        lines += ["## Skipped", ""]
        for sk in snap["skipped"]:
            lines.append(f"- {sk['backend']}/{sk['path']} at {sk['rows']:,} rows: {sk['reason']}")
        lines.append("")
    lines += ["## Environment", "", "```json", json.dumps(env, indent=1), "```", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshots", nargs="+")
    ap.add_argument("--out", default=os.path.join(common.ROOT, "BENCH.md"))
    args = ap.parse_args()
    parts = []
    for i, path in enumerate(args.snapshots):
        snap = json.load(open(path))
        snap["_file"] = os.path.relpath(path, common.ROOT)
        title = "# Benchmark results" if i == 0 else f"# Additional run: {snap['_file']}"
        parts.append(render(snap, title))
    with open(args.out, "w") as fh:
        fh.write("\n".join(parts))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
