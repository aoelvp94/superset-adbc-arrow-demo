"""Benchmark orchestrator: every (rows, backend, path) in fresh subprocesses.

* `--rounds` timed runs per combination (interleaved across paths, so drift
  hits all paths alike), after one discarded warm-up run per combination;
* one extra run with tracemalloc on (it slows Python allocation, so its
  timings are not used);
* medians are reported; min/max kept in the JSON snapshot;
* a memory guard skips combinations whose peak RSS, extrapolated linearly
  from the previous row count, would exceed --max-rss-gb.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

STAGES = ("fetch_s", "result_set_s", "ipc_s", "pandas_s", "total_ipc_s", "total_pandas_s")


DOWNSTREAM = "both"


def run_one(backend: str, path: str, rows: int, mode: str, timeout: int) -> dict:
    cmd = [sys.executable, os.path.join(common.ROOT, "bench", "run_one.py"),
           "--backend", backend, "--path", path, "--rows", str(rows), "--mode", mode,
           "--downstream", DOWNSTREAM]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    raise RuntimeError(f"{backend}/{path}/{rows} failed:\n{proc.stderr[-2000:]}")


def versions() -> dict:
    import importlib.metadata as md

    out = {"python": platform.python_version(), "platform": platform.platform()}
    for pkg in ("apache-superset", "pyarrow", "pandas", "numpy", "sqlalchemy", "duckdb",
                "duckdb-engine", "psycopg2-binary", "adbc-driver-manager",
                "adbc-driver-postgresql", "adbc-driver-flightsql", "flightsql-dbapi"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    try:
        out["superset_commit"] = open(os.path.join(common.ROOT, "SUPERSET_COMMIT")).read().strip()
    except OSError:
        out["superset_commit"] = None
    try:
        with open("/proc/cpuinfo") as fh:
            out["cpu"] = next(l.split(":", 1)[1].strip() for l in fh if l.startswith("model name"))
    except (OSError, StopIteration):
        out["cpu"] = None
    out["cpu_count"] = os.cpu_count()
    try:
        with open("/proc/meminfo") as fh:
            out["mem_total_gb"] = round(int(fh.readline().split()[1]) / 2**20, 1)
    except OSError:
        pass
    try:
        out["docker_images"] = subprocess.run(
            ["docker", "inspect", "--format", "{{.Name}} {{.Config.Image}} {{.Image}}",
             "sab-postgres", "sab-flightsql"], capture_output=True, text=True, timeout=20,
        ).stdout.strip().splitlines()
    except Exception:  # noqa: BLE001
        out["docker_images"] = None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, nargs="+", default=[100_000, 1_000_000])
    ap.add_argument("--rounds", type=int, nargs="+", default=None,
                    help="rounds per row count (default 5,3,1...)")
    ap.add_argument("--backends", nargs="+", default=list(common.BACKENDS))
    ap.add_argument("--paths", nargs="+", default=list(common.PATHS))
    ap.add_argument("--max-rss-gb", type=float, default=float(os.environ.get("BENCH_MAX_RSS_GB", "5")))
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--out", default=None)
    ap.add_argument("--downstream", default="both", choices=("both", "ipc"))
    args = ap.parse_args()
    global DOWNSTREAM
    DOWNSTREAM = args.downstream
    rounds = args.rounds or [5, 3, 1, 1, 1][: len(args.rows)]
    if len(rounds) < len(args.rows):
        rounds += [rounds[-1]] * (len(args.rows) - len(rounds))

    started = dt.datetime.now(dt.timezone.utc)
    out_path = args.out or os.path.join(
        common.ROOT, "results", f"bench-{started.strftime('%Y%m%dT%H%M%SZ')}.json")
    results: list[dict] = []
    skipped: list[dict] = []
    last_peak: dict[tuple[str, str], tuple[int, int]] = {}

    for rows, n_rounds in zip(args.rows, rounds):
        combos = []
        for backend in args.backends:
            for path in args.paths:
                prev = last_peak.get((backend, path))
                if prev:
                    est = prev[1] * rows / prev[0]
                    if est > args.max_rss_gb * 2**30:
                        skipped.append({"backend": backend, "path": path, "rows": rows,
                                        "reason": f"estimated peak RSS {est / 2**30:.1f} GiB > "
                                                  f"--max-rss-gb {args.max_rss_gb}"})
                        print(f"skip {backend}/{path}/{rows}: est {est / 2**30:.1f} GiB", flush=True)
                        continue
                combos.append((backend, path))
        for backend, path in combos:  # warm-up (server caches, OS page cache)
            run_one(backend, path, rows, "time", args.timeout)
        timed: dict[tuple[str, str], list[dict]] = {c: [] for c in combos}
        for r in range(n_rounds):
            for backend, path in combos:
                res = run_one(backend, path, rows, "time", args.timeout)
                timed[(backend, path)].append(res)
                print(f"rows={rows} round={r + 1}/{n_rounds} {backend:9} {path:9} "
                      f"total_ipc={res['total_ipc_s']:.3f}s "
                      f"peak_rss=+{res['peak_rss_delta_bytes'] / 2**20:.0f}MiB", flush=True)
        for backend, path in combos:
            mem = run_one(backend, path, rows, "mem", args.timeout)
            runs = timed[(backend, path)]
            summary = {"backend": backend, "path": path, "rows": rows, "rounds": len(runs),
                       "downstream": DOWNSTREAM}
            for k in STAGES:
                vals = [x[k] for x in runs]
                if any(v is None for v in vals):
                    summary[k] = None
                    continue
                summary[k] = {"median": statistics.median(vals), "min": min(vals), "max": max(vals)}
            peak = int(statistics.median(x["peak_rss_delta_bytes"] for x in runs))
            summary["peak_rss_delta_bytes_median"] = peak
            summary["arrow_pool_peak_bytes_median"] = int(statistics.median(x["arrow_pool_peak_bytes"] for x in runs))
            summary["tracemalloc_peak_bytes"] = mem["tracemalloc_peak_bytes"]
            summary["ipc_bytes"] = runs[0]["ipc_bytes"]
            summary["n_rows_out"] = runs[0]["n_rows_out"]
            summary["raw"] = runs
            results.append(summary)
            last_peak[(backend, path)] = (rows, peak)
        # write after every row count so partial runs are kept
        snapshot = {"started_utc": started.isoformat(), "finished_utc": None,
                    "env": versions(), "args": vars(args), "results": results, "skipped": skipped}
        with open(out_path, "w") as fh:
            json.dump(snapshot, fh, indent=1)
    snapshot["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(out_path, "w") as fh:
        json.dump(snapshot, fh, indent=1)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
