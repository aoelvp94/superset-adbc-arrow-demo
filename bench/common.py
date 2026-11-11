"""Shared helpers: Superset bootstrap, dataset SQL, connection factories.

Everything here is local-only. Services come from docker-compose.yml.
"""

from __future__ import annotations

import os
import pathlib
from typing import Any, Callable

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DUCKDB_PATH = DATA_DIR / "bench.duckdb"

PG_HOST = os.environ.get("BENCH_PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("BENCH_PG_PORT", "55442"))
PG_USER = PG_PASSWORD = PG_DB = "bench"
PG_URI = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"

FS_HOST = os.environ.get("BENCH_FLIGHTSQL_HOST", "127.0.0.1")
FS_PORT = int(os.environ.get("BENCH_FLIGHTSQL_PORT", "31347"))
FS_USER = FS_PASSWORD = "bench"

BACKENDS = ("postgres", "duckdb", "flightsql")
# rows      = the backend's classic row driver + current SupersetResultSet
# adbc_rows = ADBC driver, but still fetchall() + current SupersetResultSet
#             (diagnostic: what a sqlalchemy-adbc user gets if the result set
#             stays row-based; often slower; not a proposed feature)
# arrow     = ADBC cursor Arrow fetch + SupersetResultSet.from_arrow.
#             from_arrow accepts any pyarrow.Table. ADBC is the source this
#             harness uses, not a requirement of the constructor.
PATHS = ("rows", "adbc_rows", "arrow")

COLUMNS = ("id", "i32", "f64", "dec", "txt", "ts_tz", "ts", "d", "b", "js", "u")


def table_name(rows: int) -> str:
    return f"bench_{rows}"


def postgres_ctas(rows: int) -> str:
    return f"""
CREATE TABLE {table_name(rows)} AS
SELECT
  g::bigint                                                         AS id,
  CASE WHEN g % 7 = 0 THEN NULL ELSE (g % 100000)::int END           AS i32,
  (g * 0.5)::float8                                                  AS f64,
  CASE WHEN g % 11 = 0 THEN NULL
       ELSE ((g % 1000000) / 7.0)::numeric(18, 4) END                AS dec,
  CASE WHEN g % 13 = 0 THEN NULL ELSE 'name_' || g END               AS txt,
  timestamptz '2024-01-01 00:00:00+00' + g * interval '1 second'     AS ts_tz,
  timestamp '2024-01-01 00:00:00' + g * interval '1 second'          AS ts,
  date '2020-01-01' + (g % 3650)::int                                AS d,
  CASE g % 3 WHEN 0 THEN true WHEN 1 THEN false END                  AS b,
  CASE WHEN g % 17 = 0 THEN NULL
       ELSE json_build_object('k', g, 'tag', 'x' || (g % 10)) END    AS js,
  CASE WHEN g % 19 = 0 THEN NULL ELSE md5(g::text)::uuid END         AS u
FROM generate_series(1, {rows}) AS g
"""


def duckdb_ctas(rows: int) -> str:
    return f"""
CREATE TABLE {table_name(rows)} AS
SELECT
  g::BIGINT                                                          AS id,
  CASE WHEN g % 7 = 0 THEN NULL ELSE (g % 100000)::INTEGER END       AS i32,
  (g * 0.5)::DOUBLE                                                  AS f64,
  CASE WHEN g % 11 = 0 THEN NULL
       ELSE ((g % 1000000)::DECIMAL(18, 4) / 7)::DECIMAL(18, 4) END  AS dec,
  CASE WHEN g % 13 = 0 THEN NULL ELSE 'name_' || g END               AS txt,
  TIMESTAMPTZ '2024-01-01 00:00:00+00' + to_seconds(g)               AS ts_tz,
  TIMESTAMP '2024-01-01 00:00:00' + to_seconds(g)                    AS ts,
  DATE '2020-01-01' + (g % 3650)::INTEGER                            AS d,
  CASE g % 3 WHEN 0 THEN true WHEN 1 THEN false END                  AS b,
  CASE WHEN g % 17 = 0 THEN NULL
       ELSE json_object('k', g, 'tag', 'x' || (g % 10)) END          AS js,
  CASE WHEN g % 19 = 0 THEN NULL ELSE md5(g::VARCHAR)::UUID END      AS u
FROM range(1, {rows} + 1) AS t(g)
"""


def select_sql(rows: int) -> str:
    return f"SELECT * FROM {table_name(rows)} ORDER BY id"


# --------------------------------------------------------------------------
# Superset bootstrap
# --------------------------------------------------------------------------
_APP = None


def superset_app():
    """Create a minimal Superset app so superset.* modules import cleanly."""
    global _APP
    if _APP is None:
        os.environ.setdefault(
            "SUPERSET_CONFIG_PATH", str(ROOT / "bench" / "superset_config_bench.py")
        )
        from superset.app import create_app

        _APP = create_app()
    return _APP


def engine_spec(backend: str):
    if backend == "postgres":
        from superset.db_engine_specs.postgres import PostgresEngineSpec

        return PostgresEngineSpec
    if backend == "duckdb":
        from superset.db_engine_specs.duckdb import DuckDBEngineSpec

        return DuckDBEngineSpec
    if backend == "flightsql":
        # Superset's only Flight SQL engine spec today.
        from superset.db_engine_specs.datafusion import DataFusionEngineSpec

        return DataFusionEngineSpec
    raise ValueError(backend)


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------
def row_connection(backend: str) -> Any:
    """The driver Superset uses for this backend today (via SQLAlchemy)."""
    if backend == "postgres":
        import sqlalchemy as sa

        eng = sa.create_engine(PG_URI.replace("postgresql://", "postgresql+psycopg2://"))
        return eng.raw_connection()
    if backend == "duckdb":
        import sqlalchemy as sa

        eng = sa.create_engine(f"duckdb:///{DUCKDB_PATH}")
        conn = eng.raw_connection()
        cur = conn.cursor()
        cur.execute("SET TimeZone='UTC'")
        cur.close()
        return conn
    if backend == "flightsql":
        # flightsql-dbapi is what Superset's DataFusion spec / extra points to.
        # Its SQLAlchemy dialect is pinned to sqlalchemy<2, so we use its DB-API
        # module directly (the part that does the fetch).
        from flightsql import FlightSQLClient, connect

        client = FlightSQLClient(
            host=FS_HOST,
            port=FS_PORT,
            user=FS_USER,
            password=FS_PASSWORD,
            insecure=True,
        )
        return connect(client)
    raise ValueError(backend)


def adbc_connection(backend: str) -> Any:
    if backend == "postgres":
        import adbc_driver_postgresql.dbapi as m

        return m.connect(PG_URI)
    if backend == "duckdb":
        import adbc_driver_duckdb.dbapi as m

        conn = m.connect(str(DUCKDB_PATH))
        cur = conn.cursor()
        cur.execute("SET TimeZone='UTC'")
        cur.close()
        return conn
    if backend == "flightsql":
        import adbc_driver_flightsql.dbapi as m
        from adbc_driver_flightsql import DatabaseOptions

        return m.connect(
            f"grpc://{FS_HOST}:{FS_PORT}",
            db_kwargs={
                "username": FS_USER,
                "password": FS_PASSWORD,
            },
            autocommit=True,
        )
    raise ValueError(backend)


def connection_for(backend: str, path: str) -> Any:
    return row_connection(backend) if path == "rows" else adbc_connection(backend)
