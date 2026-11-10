"""Create the benchmark tables (idempotent) in Postgres, DuckDB and Flight SQL.

Data is generated server-side with generate_series/range, so setup time does
not depend on the client and the same rows exist for every path.
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import common  # noqa: E402


def _exists_pg(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (name,))
    return cur.fetchone()[0] is not None


def setup_postgres(rows: int) -> None:
    import psycopg2

    conn = psycopg2.connect(common.PG_URI)
    conn.autocommit = True
    cur = conn.cursor()
    if not _exists_pg(cur, common.table_name(rows)):
        t = time.perf_counter()
        cur.execute(common.postgres_ctas(rows))
        cur.execute(f"ANALYZE {common.table_name(rows)}")
        print(f"postgres {rows:>10,} rows created in {time.perf_counter() - t:.1f}s")
    conn.close()


def _duckdb_like(cur, rows: int, label: str) -> None:
    name = common.table_name(rows)
    cur.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ) if label == "duckdb" else cur.execute(
        f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{name}'"
    )
    if cur.fetchone()[0] == 0:
        t = time.perf_counter()
        cur.execute(common.duckdb_ctas(rows))
        print(f"{label} {rows:>10,} rows created in {time.perf_counter() - t:.1f}s")


def setup_duckdb(rows: int) -> None:
    import duckdb

    common.DATA_DIR.mkdir(exist_ok=True)
    conn = duckdb.connect(str(common.DUCKDB_PATH))
    conn.execute("SET TimeZone='UTC'")
    _duckdb_like(conn, rows, "duckdb")
    conn.close()


def setup_flightsql(rows: int) -> None:
    conn = common.adbc_connection("flightsql")
    cur = conn.cursor()
    cur.execute("SET TimeZone='UTC'")
    _duckdb_like(cur, rows, "flightsql")
    cur.close()
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, nargs="+", default=[1000, 100_000, 1_000_000])
    ap.add_argument("--backends", nargs="+", default=list(common.BACKENDS))
    args = ap.parse_args()
    fns = {"postgres": setup_postgres, "duckdb": setup_duckdb, "flightsql": setup_flightsql}
    for rows in args.rows:
        for b in args.backends:
            fns[b](rows)
    print("setup ok")


if __name__ == "__main__":
    main()
