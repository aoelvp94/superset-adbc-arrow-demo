# Superset Arrow ingest prototype

Personal prototype of an opt-in Arrow ingest path for
[Apache Superset](https://github.com/apache/superset):
`SupersetResultSet.from_arrow` beside the current row-based `fetchall()` path.
It is Aldo Escobar's demo, not an Apache project and not a pull request against
apache/superset. Nothing in this tree is filed upstream.

Everything runs locally. Postgres and a [GizmoSQL](https://github.com/gizmosql/gizmosql)
Flight SQL server run in Docker; DuckDB is a file on disk.

## Two layers

Query results are still expensive in two different places. This repo is only the
first of them.

**Ingest (this repo).** `SupersetResultSet` is usually built from Python rows,
even when the engine can already produce a `pyarrow.Table`. `from_arrow` accepts
that Table from any source. ADBC is one way to obtain a Table. DuckDB
(`to_arrow_reader` / `to_arrow_table`), Flight SQL, and any other cursor or
SQLAlchemy execution that can return a Table use the same constructor. Engines
that cannot stay on `fetchall`.

**Wire format (not this repo).** `/api/v1/chart/data` still sends JSON row
objects. Evan Rusackas's draft
[apache/superset#45363](https://github.com/apache/superset/pull/45363) is the
opt-in Arrow IPC response on that endpoint, plus a frontend shim that turns the
bytes back into the row objects plugins already consume. This demo does not
change that API or the shim. SQL Lab's results grid still receives JSON row
objects: `_serialize_and_expand_data` still calls `to_pandas_df()` and
`df_to_records` unless the results backend is storing IPC. The two pieces are
complementary: #45363 is how an opted-in chart asks for Arrow on the wire; this
patch is how the backend can build the result set without paying `fetchall`
first. Superset's chart query path still converts the result set to a DataFrame
inside `Database.get_df` before the rest of chart code runs. This patch leaves
that conversion in place. SQL Lab's synchronous JSON payload does the same
after the result set exists.

## Opt-in

The row path is the default and the fallback.

* `BaseEngineSpec.supports_arrow_result` defaults to `False`. An engine spec
  sets it `True` to opt in. This patch does that for PostgreSQL, DuckDB
  (MotherDuck inherits it), and a sketch Flight SQL spec. Other engines stay
  on `fetch_data`.
* Feature flag `ARROW_NATIVE_RESULT_SET` defaults to `False`. It is a global
  rollback, not the per-engine switch. `Database.get_df` (chart and dataset
  queries) and SQL Lab execute call `maybe_fetch_arrow` only when the flag is
  on, and that method still returns `None` unless the engine opted in and the
  cursor can produce a Table. psycopg2 has no Arrow fetch, so a normal
  PostgreSQL connection stays on rows even when both switches are on.
* SQL Lab execute uses that same gate in both places that build a result set:
  `sql_lab._read_sqllab_payload` (the `/api/v1/sqllab/execute` path) and
  `sql.execution.executor._result_set_for_statement` (synchronous
  `Database.execute` and the async Celery task). The row path is what runs
  when the gate declines, including its limit trim and, on the executor, the
  `_LimitedCursor` truncation probe. Column-description probes in
  `connectors/sqla/utils.py` stay on `fetch_data`. `get_df` is also used by
  alerts and SQL Lab export, so those callers share the gate once the flag
  is on.

`adbc_rows` in the harness is a diagnostic. It is an ADBC cursor fed through
today's `fetchall()` and the row constructor, which is what a `sqlalchemy-adbc`
connection gets if the result set stays row-based. It is often slower than the
classic row driver. It is not a proposed feature.

## What the snapshot measured

The numbers below are the 2026-11-14 run against apache/superset master
`f81191d55eef3e0fa3ae04b1c83d4e474a2a392a` plus the patch in this tree, the
same patch that #5–#7 built, applied cleanly. The previous snapshot (2026-11-10,
pin `a131fcb`, different machine) is kept in
[`results/archive/2026-11-10-a131fcb/`](results/archive/2026-11-10-a131fcb/)
for comparison; it is not what the tables below report. The Arrow path is an
ADBC `fetch_record_batch` into `from_arrow`. The constructor also accepts
DuckDB's `to_arrow_reader` / `to_arrow_table` and a full `fetch_arrow_table`.

Three fetch paths, same SQL, same tables:

| path | Driver | Result-set constructor | Meaning |
|---|---|---|---|
| `rows` | The driver Superset uses today (psycopg2, duckdb-engine, flightsql-dbapi) | current `SupersetResultSet(...)` | The baseline. |
| `adbc_rows` | ADBC | still `cursor.fetchall()` + current `SupersetResultSet(...)` | Diagnostic only. |
| `arrow` | ADBC | Arrow fetch + `SupersetResultSet.from_arrow(...)` | The ingest path under test. |

Each measurement is a **fresh Python process**. Stages (wall clock,
`perf_counter`):

| stage | What is timed |
|---|---|
| fetch | `cursor.execute` plus the fetch (`engine_spec.fetch_data` or `fetch_arrow`) |
| result set | constructing `SupersetResultSet` / `from_arrow`, plus `.columns` |
| IPC | `superset.sqllab.utils.write_ipc_buffer(pa_table)` — the async SQL Lab default (`RESULTS_BACKEND_USE_MSGPACK=True`) |

`total (IPC)` = fetch + result set + IPC. One discarded warm-up runs first;
then `--rounds` timed runs (interleaved across paths). Tables report the
**median**. A separate process enables tracemalloc; those timings are
discarded, only the Python-heap peak is kept (Arrow/ADBC C buffers are not
traced). Peak RSS is the resident-memory high-water mark above the RSS just
before the query. On Linux the mark is reset first (`VmHWM`). On macOS it
cannot be reset, so it also covers imports in the worker process; compare it
across paths only.

`total (pandas)` = fetch + result set + Superset's own `to_pandas_df()`, the
DataFrame that `Database.get_df` hands to chart code. The patch does not change
that conversion; it is measured so the chart-path gain is not overstated.
`results/BENCH.md` is the mechanical render of the same JSON.

The dataset is one table per size: 11 columns (`id`, `i32`, `f64`, `dec`,
`txt`, `ts_tz`, `ts`, `d`, `b`, `js`, `u`) with periodic NULLs, generated
deterministically in each engine.

## Layout

| Path | Purpose |
|---|---|
| `patches/0001-arrow-native-result-set.patch` | Ingest patch against the commit in `SUPERSET_COMMIT`. See `patches/README.md`. |
| `SUPERSET_COMMIT` | `f81191d55eef3e0fa3ae04b1c83d4e474a2a392a` (apache/superset master on 2026-11-14). |
| `bench/run_bench.py`, `bench/run_one.py` | Fresh-process harness and one-shot worker. |
| `bench/setup_data.py`, `bench/common.py` | Table generation and connection factories. |
| `bench/parity.py`, `tests/` | Live type-parity comparison and constructor tests. |
| `bench/render.py` | Renders `results/BENCH.md` from the JSON snapshots (numbers only from JSON). |
| `docker-compose.yml`, `docker/flightsql/` | Postgres 17.6 and GizmoSQL 1.42.2. |
| `justfile` | Setup, tests, bench, and render entry points. |
| `results/` | Committed snapshots from the 2026-11-14 run, plus `pip-freeze.txt`. Older runs are in `results/archive/`. |
| `docs/type-parity.md` | Observed type differences between the row and Arrow paths. |
| `evidence/task-a/` | Does `apache-superset[datafusion]` resolve? (It does not, today.) |

## Reproduce

You need Python 3.11 (fetched by [uv](https://github.com/astral-sh/uv)),
[just](https://github.com/casey/just), Docker (Compose v2), and git.

If your Docker daemon is not on the default socket, export `DOCKER_HOST`
first, e.g. `export DOCKER_HOST=tcp://127.0.0.1:2375`.

```bash
just up                 # Postgres + GizmoSQL
just venv               # clone pinned Superset, apply the patch, install into .venv
just setup-data         # 1k / 10k / 50k / 100k / 1M / 10M tables in each backend
just test               # constructor tests; golden type-parity needs the services
just parity             # writes results/type-parity.json
```

The committed snapshots (2026-11-14) came from:

```bash
just bench          # 10k/50k/100k × 5 rounds, 1M × 3; all backends × all paths
just bench-large    # Arrow only, IPC only: 1M and a 10M attempt (skipped by the guard)
mv results/bench-latest.json results/bench-main.json
mv results/bench-large-latest.json results/bench-large-ipc.json
.venv/bin/python bench/render.py results/bench-main.json results/bench-large-ipc.json \
    --out results/BENCH.md
```
`just bench-quick` is a short sanity run (100k rows, 2 rounds).
`just reproduce` runs services, venv, data, tests, parity, both benches, and render.

## Environment

Measured on 2026-11-14 on an Apple M4 (10 cores, 24 GiB RAM), macOS 26.5.2,
Python 3.11.14, with Postgres and GizmoSQL in Docker Desktop (arm64 images).
No other benchmark or test ran during the measurement. Absolute times are not
comparable with the 2026-11-10 snapshot, which ran on a shared 8-vCPU Linux
Xeon; compare paths inside one snapshot. Versions are pinned in
`requirements.txt` and recorded in each JSON snapshot.

| Component | Version |
|---|---|
| apache/superset | `f81191d55eef3e0fa3ae04b1c83d4e474a2a392a` + `patches/0001-arrow-native-result-set.patch` |
| pandas / numpy | 3.1.1 / 2.4.6 (Superset's own requirements) |
| pyarrow | 26.0.1 |
| SQLAlchemy | 2.0.57 |
| duckdb / duckdb-engine | 1.5.6 / 0.17.0 |
| psycopg2-binary | 2.9.13 |
| adbc-driver-manager / postgresql / flightsql | 1.13.0 |
| flightsql-dbapi | 0.2.2 (installed with `--no-deps`; it pins SQLAlchemy &lt; 2, which Superset master rejects) |
| Postgres image | `postgres:17.6` |
| Flight SQL image | GizmoSQL 1.42.2 (`sab-flightsql:gizmosql-1.42.2-json`) |

The full `pip freeze` from that run is in [`results/pip-freeze.txt`](results/pip-freeze.txt).

## Results

All numbers below are medians copied from the JSON snapshots. The mechanical
render is [`results/BENCH.md`](results/BENCH.md).

### Speedup across sizes

Source: [`results/bench-main.json`](results/bench-main.json) (2026-11-14,
15:04–15:42 UTC). 5 rounds at 10k, 50k and 100k rows; 3 rounds at 1M.
`rows` is the driver Superset uses today; `arrow` is `from_arrow`.

| rows | backend | rows: total IPC (s) | arrow: total IPC (s) | speedup (IPC) | speedup (pandas) |
|---:|---|---:|---:|---:|---:|
| 10,000 | postgres | 0.130 | 0.026 | 5.0× | 3.8× |
| 10,000 | duckdb | 0.077 | 0.005 | 16.7× | 10.8× |
| 10,000 | flightsql | 0.183 | 0.038 | 4.7× | 4.2× |
| 50,000 | postgres | 0.552 | 0.102 | 5.4× | 3.6× |
| 50,000 | duckdb | 0.364 | 0.012 | 30.9× | 18.4× |
| 50,000 | flightsql | 0.653 | 0.087 | 7.5× | 7.0× |
| 100,000 | postgres | 1.101 | 0.175 | 6.3× | 4.3× |
| 100,000 | duckdb | 0.657 | 0.020 | 32.7× | 20.8× |
| 100,000 | flightsql | 1.268 | 0.114 | 11.1× | 10.4× |
| 1,000,000 | postgres | 13.36 | 1.25 | 10.7× | 6.6× |
| 1,000,000 | duckdb | 5.83 | 0.22 | 26.8× | 22.2× |
| 1,000,000 | flightsql | 11.09 | 0.59 | 18.7× | 18.0× |

`speedup (pandas)` uses `total (pandas)`: what the chart path pays before chart
code runs. It is lower than the IPC speedup because `to_pandas_df()` is the same
work on both paths and becomes a larger share once ingest is cheap (Postgres at
1M: 0.89 s of the Arrow path's 2.02 s).

### 1,000,000 rows, all paths

| backend | path | fetch (s) | result set (s) | IPC (s) | **total IPC (s)** | speedup vs rows (IPC) | total pandas (s) | peak RSS (MiB) | tracemalloc (MiB) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | 4.43 | 8.87 | 0.11 | **13.36** | 1.0× | 13.38 | 1602 | 1197 |
| postgres | adbc_rows | 12.44 | 2.45 | 0.04 | **14.78** | 0.9× | 14.77 | 959 | 870 |
| postgres | arrow | 0.95 | 0.15 | 0.10 | **1.25** | 10.7× | 2.02 | 837 | 470 |
| duckdb | rows | 3.12 | 2.67 | 0.04 | **5.83** | 1.0× | 5.90 | 1148 | 897 |
| duckdb | adbc_rows | 9.47 | 1.61 | 0.03 | **11.15** | 0.5× | 11.23 | 861 | 763 |
| duckdb | arrow | 0.12 | &lt;0.01 | 0.09 | **0.22** | 26.8× | 0.27 | 793 | 124 |
| flightsql | rows | 3.17 | 7.86 | 0.04 | **11.09** | 1.0× | 11.15 | 1438 | 1238 |
| flightsql | adbc_rows | 7.80 | 1.75 | 0.03 | **9.60** | 1.2× | 9.67 | 893 | 763 |
| flightsql | arrow | 0.50 | &lt;0.01 | 0.10 | **0.59** | 18.7× | 0.62 | 698 | 124 |

Most of the gain is in fetch (record batches instead of `fetchall()`) and in
result-set construction (`from_arrow` instead of building the result set from
Python rows). `adbc_rows` is usually slower than `rows`: the ADBC driver still
has to convert Arrow to Python rows for today's constructor.

### Arrow only, IPC only: 1M

[`results/bench-large-ipc.json`](results/bench-large-ipc.json), 3 rounds
(15:42–15:44 UTC). `--downstream ipc` stops after `write_ipc_buffer`.

| backend | **total IPC (s)** | fetch (s) | result set (s) | IPC (s) | peak RSS (MiB) |
|---|---:|---:|---:|---:|---:|
| postgres | **1.28** | 1.03 | 0.19 | 0.14 | 590 |
| duckdb | **0.24** | 0.14 | &lt;0.01 | 0.10 | 730 |
| flightsql | **1.06** | 0.95 | &lt;0.01 | 0.13 | 544 |

Postgres and DuckDB agree with the all-path run (1.28 vs 1.25, 0.24 vs 0.22).
Flight SQL fetch varied between the two runs (0.95 s vs 0.50 s), so treat its
1M Arrow figure as 0.6–1.1 s; it is 10–19× the row path either way.

### 10M rows: skipped

The 10M attempt was **not run**. The harness extrapolates peak RSS from the
previous size and skipped every backend against `--max-rss-gb 5`: postgres
5.8 GiB, duckdb 7.1 GiB, flightsql 5.3 GiB (estimates). On macOS the peak
includes worker start-up, so these estimates are conservative.

## Caveats

- **This is a personal prototype, not a Superset PR.** The patch applies to
  the commit in `SUPERSET_COMMIT` and is documented in `patches/README.md`.
  Behaviour can still move if this is proposed upstream later.
- **The figures are from 2026-11-14 on `f81191d`**, on one Apple M4 laptop.
  The 2026-11-10 snapshot on `a131fcb` (Linux Xeon) is archived; its 1M
  speedups were larger (11.5× / 32× / 44.7×). On this machine the row baseline
  is 1.5–2.2× faster (13.4 / 5.8 / 11.1 s vs 19.9 / 12.8 / 21.5 s), while the
  Arrow path moved less (1.25 / 0.22 / 0.59 s vs 1.73 / 0.40 / 0.48 s).
- **`adbc_rows` is not a proposed feature.** It separates "use an ADBC driver"
  from "use `from_arrow`". It is often slower than the classic row driver.
- **10M was skipped**, as above, to stay under a 5 GiB RSS guard.
- **Single laptop run.** Treat absolute seconds as indicative and compare paths
  inside one snapshot.
- **Flight SQL `rows` vs `arrow` are not the same client.** `rows` uses
  `flightsql-dbapi` (the library Superset's DataFusion extra points at) plus
  `DataFusionEngineSpec`. `arrow` / `adbc_rows` use `adbc-driver-flightsql`
  and the sketch `FlightSQLEngineSpec` in the patch. The server is the same
  GizmoSQL process.
- **Type parity is not bit-identical in every column.** Known, pinned
  divergences (integer width, decimal precision metadata, JSON whitespace in
  the IPC payload, some Flight SQL date conversions) are
  listed in [`docs/type-parity.md`](docs/type-parity.md) and asserted by
  `just test` when the services are up. Postgres interval values match the
  psycopg2 row path live (`1 day 02:03:04` is 93784000.0 ms); the golden was
  regenerated on 2026-11-14. Constructor tests that do not need services live
  in `tests/test_from_arrow_unit.py`.
- **UUID stringification is vectorized in the patch** (NumPy, not the
  per-value Python loop in `stringify_extension_columns`). That loop
  dominated the Postgres Arrow result-set stage before the change. A
  snapshot taken before that change is in
  `results/archive/bench-before-vectorized-uuid.json`.

## License

The benchmark code in this repository is provided for reproduction and
discussion. Apache Superset is Apache-2.0 and is not vendored here; it is
cloned at the pinned commit by `just venv`.
