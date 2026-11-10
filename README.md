# Superset Arrow-native result-set bench

Local prototype and benchmark of an Arrow-native result path for
[Apache Superset](https://github.com/apache/superset):
`SupersetResultSet.from_arrow` versus the current row-based `fetchall()`
path. It measures wall-clock time and peak memory on three backends
(Postgres, DuckDB, Flight SQL) and records type-parity between the paths.

Everything runs locally. Postgres and a [GizmoSQL](https://github.com/gizmosql/gizmosql)
Flight SQL server run in Docker; DuckDB is a file on disk. There are no cloud
credentials, no employer or product branding, and nothing in this tree is
pushed anywhere by default.

The prototype patch lives in `patches/` and is **not submitted upstream**.
This repo is a measurement and a discussion piece, not an Apache Superset PR.

## What it measures

Three fetch paths, same SQL, same tables:

| path | Driver | Result-set constructor | Meaning |
|---|---|---|---|
| `rows` | The driver Superset uses today (psycopg2, duckdb-engine, flightsql-dbapi) | current `SupersetResultSet(...)` | The baseline. |
| `adbc_rows` | [ADBC](https://arrow.apache.org/adbc/) (`adbc-driver-postgresql` / DuckDB / Flight SQL) | still `cursor.fetchall()` + current `SupersetResultSet(...)` | What a `sqlalchemy-adbc` user gets on Superset master today: Arrow on the wire, then Python rows. Isolates "switch the driver" from "switch the result set". |
| `arrow` | ADBC | `cursor.fetch_record_batch()` + prototype `SupersetResultSet.from_arrow(...)` | The proposed path: Arrow end to end, no Python row materialization. |

Each measurement is a **fresh Python process**. Stages (wall clock,
`perf_counter`):

| stage | What is timed |
|---|---|
| fetch | `cursor.execute` plus the fetch (`engine_spec.fetch_data` or `fetch_arrow`) |
| result set | constructing `SupersetResultSet` / `from_arrow`, plus `.columns` (SQL Lab column metadata) |
| IPC | `superset.sqllab.utils.write_ipc_buffer(pa_table)` — the async SQL Lab default (`RESULTS_BACKEND_USE_MSGPACK=True`) |
| pandas | Superset's own `result_set.to_pandas_df()` — the sync SQL Lab / chart-data path. Skipped with `--downstream ipc`. |

`total (IPC)` = fetch + result set + IPC. `total (pandas)` = fetch + result set +
`to_pandas_df()`. One discarded warm-up runs first; then `--rounds` timed runs
(interleaved across paths). Tables report the **median**. A separate process
enables tracemalloc; those timings are discarded, only the Python-heap peak is
kept (Arrow/ADBC C buffers are not traced). Peak RSS is the resident-memory
high-water mark above the RSS just before the query (`VmHWM` reset on Linux).

The dataset is one table per size: 11 columns (`id`, `i32`, `f64`, `dec`,
`txt`, `ts_tz`, `ts`, `d`, `b`, `js`, `u`) with periodic NULLs, generated
deterministically in each engine.

## Layout

| Path | Purpose |
|---|---|
| `patches/0001-arrow-native-result-set.patch` | Local prototype against the pinned Superset commit. See `patches/README.md`. |
| `SUPERSET_COMMIT` | `a131fcb623d88ed9eb7e7a414e226437423d645c` (apache/superset master at the time of the run). |
| `bench/run_bench.py`, `bench/run_one.py` | Fresh-process harness and one-shot worker. |
| `bench/setup_data.py`, `bench/common.py` | Table generation and connection factories. |
| `bench/parity.py`, `tests/` | Type-parity comparison and golden tests. |
| `bench/render.py` | Renders `results/BENCH.md` from the JSON snapshots (numbers only from JSON). |
| `docker-compose.yml`, `docker/flightsql/` | Postgres 17.6 and GizmoSQL 1.42.2. |
| `justfile` | Setup, tests, bench, and render entry points. |
| `results/` | Committed snapshots from the run below, plus `pip-freeze.txt`. |
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
just setup-data         # 1k / 100k / 1M / 10M tables in each backend
just test               # unit + golden type-parity tests
just parity             # writes results/type-parity.json
```

Exact commands that produced the committed snapshots (2026-11-10):

```bash
# 100k × 5 rounds and 1M × 3 rounds; all backends × all paths;
# both downstreams (IPC and Superset's to_pandas_df). Time + memory.
.venv/bin/python bench/run_bench.py \
    --rows 100000 1000000 --rounds 5 3 \
    --max-rss-gb 5 --downstream both \
    --out results/bench-main.json

# Arrow path only, IPC downstream only: 1M and a 10M attempt.
# 10M was skipped by the memory guard (see Results).
.venv/bin/python bench/run_bench.py \
    --rows 1000000 10000000 --rounds 3 3 \
    --paths arrow --downstream ipc --max-rss-gb 5 \
    --out results/bench-large-ipc.json

# Arrow path only, IPC downstream only, 3M rows (fits under the 5 GiB guard).
.venv/bin/python bench/run_bench.py \
    --rows 3000000 --rounds 3 \
    --paths arrow --downstream ipc --max-rss-gb 5 \
    --out results/bench-large-ipc-3m.json

.venv/bin/python bench/render.py \
    results/bench-main.json \
    results/bench-large-ipc.json \
    results/bench-large-ipc-3m.json \
    --out results/BENCH.md
```

`just bench` and `just bench-large` run the same harness with default output
names (`results/bench-latest.json`, `results/bench-large-latest.json`).
`just bench-quick` is a ~2 minute sanity run (100k rows, 2 rounds).
`just reproduce` runs services, venv, data, tests, parity, both benches, and render.

## Environment

Measured on 2026-11-10 (Asia/Yerevan) on an 8-vCPU `Intel(R) Xeon(R) Processor`
box with 15.6 GiB RAM, Linux 6.12, Python 3.11.17. Other workloads were
running on the same machine, so **absolute times are noisy**; the useful
signal is the comparison across paths in the same run. Versions pinned in
`requirements.txt` and recorded in each JSON snapshot:

| Component | Version |
|---|---|
| apache/superset | `a131fcb623d88ed9eb7e7a414e226437423d645c` + `patches/0001-arrow-native-result-set.patch` (installed as `0.0.0.dev0`) |
| pyarrow | 26.0.1 |
| numpy | 2.4.6 |
| pandas | 3.1.1 (a Superset dependency; see caveats) |
| SQLAlchemy | 2.0.57 |
| duckdb / duckdb-engine | 1.5.6 / 0.17.0 |
| psycopg2-binary | 2.9.13 |
| adbc-driver-manager / postgresql / flightsql | 1.13.0 |
| flightsql-dbapi | 0.2.2 (installed with `--no-deps`; it pins SQLAlchemy &lt; 2, which Superset master rejects) |
| Postgres image | `postgres:17.6` |
| Flight SQL image | GizmoSQL 1.42.2 (`sab-flightsql:gizmosql-1.42.2-json`) |

The full `pip freeze` is in [`results/pip-freeze.txt`](results/pip-freeze.txt).

## Results

All numbers below are medians copied from the JSON snapshots. The mechanical
render (every stage, min/max are in the raw JSON) is
[`results/BENCH.md`](results/BENCH.md).

### 1,000,000 rows, all paths, IPC + pandas downstreams

Source: [`results/bench-main.json`](results/bench-main.json), 3 rounds, started
11:34 and finished 12:06 (Asia/Yerevan). `total (IPC)` is the headline
comparison (async SQL Lab default).

| backend | path | fetch (s) | result set (s) | IPC (s) | pandas (s) | **total IPC (s)** | total pandas (s) | speedup vs rows (IPC) | peak RSS (MiB) | tracemalloc (MiB) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | 8.30 | 11.38 | 0.22 | 0.27 | **19.90** | 19.95 | 1.0× | 1884 | 1197 |
| postgres | adbc_rows | 21.78 | 4.50 | 0.23 | 0.06 | **26.51** | 26.33 | 0.8× | 1082 | 870 |
| postgres | arrow | 1.07 | 0.35 | 0.27 | 1.57 | **1.73** | 2.98 | 11.5× | 1010 | 470 |
| duckdb | rows | 7.28 | 5.25 | 0.21 | 0.27 | **12.77** | 12.82 | 1.0× | 1328 | 897 |
| duckdb | adbc_rows | 14.57 | 2.51 | 0.20 | 0.27 | **17.28** | 17.36 | 0.7× | 1203 | 763 |
| duckdb | arrow | 0.22 | &lt;0.001 | 0.17 | 0.27 | **0.40** | 0.49 | 32.0× | 894 | 124 |
| flightsql | rows | 5.97 | 15.26 | 0.20 | 0.26 | **21.46** | 21.48 | 1.0× | 1618 | 1238 |
| flightsql | adbc_rows | 15.30 | 3.16 | 0.20 | 0.29 | **18.64** | 18.72 | 1.2× | 1024 | 763 |
| flightsql | arrow | 0.24 | &lt;0.001 | 0.24 | 0.28 | **0.48** | 0.52 | 44.7× | 697 | 124 |

Arrow is 11.5× / 32.0× / 44.7× faster than the current row path on
Postgres / DuckDB / Flight SQL at this size, measured at `total (IPC)`.
Most of the gain is in fetch (record batches instead of `fetchall()`) and in
result-set construction (`from_arrow` instead of building the result set from
Python rows). `adbc_rows` is usually *slower* than `rows`: the ADBC driver
still has to convert Arrow to Python rows for today's constructor, so you pay
for both representations.

The same run at 100,000 rows (5 rounds) is in the JSON and in
`results/BENCH.md`. Directionally the same: Postgres 1.93 s vs 0.18 s,
DuckDB 1.32 s vs 0.058 s, Flight SQL 2.24 s vs 0.068 s (`total IPC`, rows vs
arrow).

### Arrow only, IPC only: 1M and 3M

`--downstream ipc` skips Superset's `to_pandas_df()`, which is what you want
when the async SQL Lab path is the product question, and it is the only way
the Arrow path fits in memory at a few million rows.

1,000,000 rows, 3 rounds, [`results/bench-large-ipc.json`](results/bench-large-ipc.json)
(12:06–12:07 Asia/Yerevan):

| backend | **total IPC (s)** | fetch (s) | result set (s) | IPC (s) | peak RSS (MiB) |
|---|---:|---:|---:|---:|---:|
| postgres | **1.76** | 1.17 | 0.34 | 0.26 | 607 |
| duckdb | **0.47** | 0.29 | &lt;0.001 | 0.17 | 743 |
| flightsql | **0.50** | 0.26 | &lt;0.001 | 0.24 | 546 |

3,000,000 rows, 3 rounds, [`results/bench-large-ipc-3m.json`](results/bench-large-ipc-3m.json)
(12:10–12:12 Asia/Yerevan). This run finished; it was not retried.

| backend | **total IPC (s)** | fetch (s) | result set (s) | IPC (s) | peak RSS (MiB) | IPC payload (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| postgres | **4.85** | 3.33 | 1.10 | 0.53 | 1219 | 408 |
| duckdb | **1.38** | 0.79 | &lt;0.001 | 0.51 | 1906 | 390 |
| flightsql | **1.12** | 0.63 | &lt;0.001 | 0.52 | 1347 | 390 |

The 1M IPC-only totals agree with the all-path run to within ordinary
run-to-run noise (1.76 vs 1.73, 0.47 vs 0.40, 0.50 vs 0.48). Peak RSS is
lower here because `to_pandas_df()` is not run (Postgres 607 MiB vs 1010 MiB
at 1M).

### 10M rows: skipped

The 10M Arrow / IPC attempt in `bench-large-ipc.json` was **not run**. The
harness extrapolates peak RSS linearly from the previous size and skipped
every backend against `--max-rss-gb 5`:

- postgres: estimated 5.9 GiB
- duckdb: estimated 7.3 GiB
- flightsql: estimated 5.3 GiB

The 3M peaks (1.2–1.9 GiB) are consistent with that extrapolation. A machine
with more headroom could rerun with a higher `--max-rss-gb`.

## Caveats

- **This is a prototype, not a Superset PR.** The patch is applied to a
  pinned master commit in `.cache/superset` and is documented in
  `patches/README.md`. Behaviour, API shape, and engine-spec coverage can
  change if this is ever proposed upstream.
- **`adbc_rows` is not a proposed feature.** It exists only to separate
  "use an ADBC driver" from "use `from_arrow`". On current Superset it is
  the path you get if you point a database at ADBC and leave the result-set
  constructor alone, and it is often slower than the classic row driver.
- **Pandas in Superset, not in this repo's code.** The harness and the
  type-parity tests do not import pandas. They call Superset's own
  `to_pandas_df()` / `df_to_records()` when measuring or comparing the sync
  path. Apache Superset itself depends on pandas (3.1.1 in this venv), and
  `flightsql-dbapi` can return `pandas.Timestamp` values on the `rows` path.
  `--downstream ipc` never calls `to_pandas_df()`.
- **10M was skipped**, as above, to stay under a 5 GiB RSS guard on a 15.6
  GiB box.
- **Shared machine.** Other benches ran concurrently, so treat absolute
  seconds as noisy. Compare paths inside one snapshot.
- **Flight SQL `rows` vs `arrow` are not the same server client.** `rows`
  uses `flightsql-dbapi` (the library Superset's DataFusion extra points at)
  plus `DataFusionEngineSpec`. `arrow` / `adbc_rows` use
  `adbc-driver-flightsql` and the sketch `FlightSQLEngineSpec` in the patch.
  The server is the same GizmoSQL process.
- **Type parity is not bit-identical in every column.** Known, pinned
  divergences (integer width, decimal precision metadata, JSON whitespace in
  the IPC payload, interval handling, some Flight SQL date conversions) are
  listed in [`docs/type-parity.md`](docs/type-parity.md) and asserted by
  `just test`. Interval is an open gap in the prototype.
- **UUID stringification is vectorized in the patch** (NumPy, not the
  per-value Python loop in `stringify_extension_columns`). That loop
  dominated the Postgres Arrow result-set stage before the change. A
  snapshot taken before that change is in
  `results/archive/bench-before-vectorized-uuid.json`.

## License

The benchmark code in this repository is provided for reproduction and
discussion. Apache Superset is Apache-2.0 and is not vendored here; it is
cloned at the pinned commit by `just venv`.
