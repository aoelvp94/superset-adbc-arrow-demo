"""One measurement in a fresh interpreter: backend x path x rows x mode.

Prints a single JSON line. Run through bench/run_bench.py.

Stages (wall clock, perf_counter):
  fetch      cursor.execute + fetch (rows: engine_spec.fetch_data,
             arrow: engine_spec.fetch_arrow; ADBC uses fetch_record_batch)
  result_set SupersetResultSet(...) or SupersetResultSet.from_arrow(...),
             plus .columns (column metadata on the result set)
  ipc        superset.sqllab.utils.write_ipc_buffer(pa_table)  (the
             RESULTS_BACKEND_USE_MSGPACK=True path, Superset's default)
  pandas     result_set.to_pandas_df()  (Superset's own pandas conversion for
             the sync path / chart data; skipped with --downstream ipc)
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def reset_peak_rss() -> bool:
    """Reset VmHWM (Linux >= 4.0) so the peak covers only the measured work."""
    try:
        with open("/proc/self/clear_refs", "w") as fh:
            fh.write("5")
        return True
    except OSError:
        return False


def peak_rss_bytes() -> int:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("VmHWM not available")


def rss_bytes() -> int:
    with open("/proc/self/statm") as fh:
        return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def spec_for(backend: str, path: str):
    if backend == "flightsql" and path != "rows":
        from superset.db_engine_specs.flightsql import FlightSQLEngineSpec

        return FlightSQLEngineSpec
    return common.engine_spec(backend)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=common.BACKENDS)
    ap.add_argument("--path", required=True, choices=common.PATHS)
    ap.add_argument("--rows", required=True, type=int)
    ap.add_argument("--mode", default="time", choices=("time", "mem"))
    ap.add_argument(
        "--downstream",
        default="both",
        choices=("both", "ipc"),
        help="ipc: stop after write_ipc_buffer (async SQL Lab default path); "
        "skips Superset's to_pandas_df() so large row counts fit in memory",
    )
    args = ap.parse_args()

    import logging

    logging.disable(logging.WARNING)
    app = common.superset_app()
    with app.app_context():
        import pyarrow as pa

        from superset.result_set import SupersetResultSet
        from superset.sqllab.utils import write_ipc_buffer

        spec = spec_for(args.backend, args.path)
        conn = common.connection_for(args.backend, args.path)
        sql = common.select_sql(args.rows)
        gc.collect()
        rss0 = rss_bytes()
        hwm_reset = reset_peak_rss()
        pool = pa.default_memory_pool()
        pool_bytes0 = pool.bytes_allocated()
        if args.mode == "mem":
            tracemalloc.start()

        t0 = time.perf_counter()
        cur = conn.cursor()
        cur.execute(sql)
        if args.path == "arrow":
            table = spec.fetch_arrow(cur)
            assert table is not None, "engine spec/cursor did not return Arrow"
            t1 = time.perf_counter()
            rs = SupersetResultSet.from_arrow(table, spec)
            del table
        else:
            data = spec.fetch_data(cur)
            description = cur.description
            t1 = time.perf_counter()
            rs = SupersetResultSet(data, description, spec)
            del data
        columns = rs.columns
        t2 = time.perf_counter()
        buf = write_ipc_buffer(rs.pa_table)
        ipc_size = buf.size
        del buf
        t3 = time.perf_counter()
        n_rows_out = rs.size
        if args.downstream == "both":
            # Superset's own pandas conversion (sync SQL Lab / chart data);
            # we only time it and never inspect the DataFrame.
            rs.to_pandas_df()
        t4 = time.perf_counter()

        out = {
            "backend": args.backend,
            "path": args.path,
            "rows": args.rows,
            "mode": args.mode,
            "downstream": args.downstream,
            "n_rows_out": int(n_rows_out),
            "n_cols": len(columns),
            "fetch_s": t1 - t0,
            "result_set_s": t2 - t1,
            "ipc_s": t3 - t2,
            "pandas_s": (t4 - t3) if args.downstream == "both" else None,
            "total_ipc_s": t3 - t0,
            "total_pandas_s": ((t2 - t0) + (t4 - t3)) if args.downstream == "both" else None,
            "ipc_bytes": ipc_size,
            "rss_baseline_bytes": rss0,
            # peak resident memory during fetch..to_pandas, above the RSS just
            # before the query (VmHWM reset via /proc/self/clear_refs)
            "peak_rss_delta_bytes": max(0, peak_rss_bytes() - rss0),
            "peak_rss_reset_ok": hwm_reset,
            "arrow_pool_peak_bytes": pool.max_memory(),
            "arrow_pool_backend": pool.backend_name,
            "arrow_pool_baseline_bytes": pool_bytes0,
        }
        if args.mode == "mem":
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            out["tracemalloc_peak_bytes"] = peak
        cur.close()
        conn.close()
    print("RESULT " + json.dumps(out))


if __name__ == "__main__":
    main()
