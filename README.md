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
change that API, the shim, or SQL Lab's results grid. The two pieces are
complementary: #45363 is how an opted-in chart asks for Arrow on the wire; this
patch is how the backend can build the result set without paying `fetchall`
first. Superset's chart query path still converts the result set to a DataFrame
inside `Database.get_df` before the rest of chart code runs. This patch leaves
that conversion in place.

## Opt-in

The row path is the default and the fallback.

* `BaseEngineSpec.supports_arrow_result` defaults to `False`. An engine spec
  sets it `True` to opt in. This patch does that for PostgreSQL, DuckDB
  (MotherDuck inherits it), and a sketch Flight SQL spec. Other engines stay
  on `fetch_data`.
* Feature flag `ARROW_NATIVE_RESULT_SET` defaults to `False`. It is a global
  rollback, not the per-engine switch. `Database.get_df` (chart and dataset
  queries) calls `maybe_fetch_arrow` only when the flag is on, and that method
  still returns `None` unless the engine opted in and the cursor can produce a
  Table. psycopg2 has no Arrow fetch, so a normal PostgreSQL connection stays
  on rows even when both switches are on.
* SQL Lab's execute path (`sql_lab.py`, `sql/execution/executor.py`) is
  unchanged and still uses `fetch_data`. `get_df` is also used by alerts and
  SQL Lab export, so those callers share the gate once the flag is on.

`adbc_rows` in the harness is a diagnostic. It is an ADBC cursor fed through
today's `fetchall()` and the row constructor, which is what a `sqlalchemy-adbc`
connection gets if the result set stays row-based. It is often slower than the
classic row driver. It is not a proposed feature.

## What the snapshot measured

The numbers below are the 2026-11-10 run against apache/superset
`a131fcb623d88ed9eb7e7a414e226437423d645c` plus the patch as it was that day.
This branch retargets the patch onto master
`7d715a82a69a40389d0f4ce20f0e8ccfb17ce889` (2026-11-11) and does not replace
those snapshots. No 1M re-bench was run. The Arrow path in that run was an ADBC
`fetch_record_batch` into `from_arrow`. ADBC cursors still take that method;
the constructor now also accepts DuckDB's `to_arrow_reader` / `to_arrow_table`
and a full `fetch_arrow_table`.

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
before the query (`VmHWM` reset on Linux).

The JSON snapshots also record Superset's synchronous chart-data conversion
after the result set. This patch does not change that step, and those fields
were not re-measured. `results/BENCH.md` is the mechanical render of the same
run and was not regenerated.

The dataset is one table per size: 11 columns (`id`, `i32`, `f64`, `dec`,
`txt`, `ts_tz`, `ts`, `d`, `b`, `js`, `u`) with periodic NULLs, generated
deterministically in each engine.

## Layout

| Path | Purpose |
|---|---|
| `patches/0001-arrow-native-result-set.patch` | Ingest patch against the commit in `SUPERSET_COMMIT`. See `patches/README.md`. |
| `SUPERSET_COMMIT` | `7d715a82a69a40389d0f4ce20f0e8ccfb17ce889` (apache/superset master on 2026-11-11). |
| `bench/run_bench.py`, `bench/run_one.py` | Fresh-process harness and one-shot worker. |
| `bench/setup_data.py`, `bench/common.py` | Table generation and connection factories. |
| `bench/parity.py`, `tests/` | Live type-parity comparison and constructor tests. |
| `bench/render.py` | Renders `results/BENCH.md` from the JSON snapshots (numbers only from JSON). |
| `docker-compose.yml`, `docker/flightsql/` | Postgres 17.6 and GizmoSQL 1.42.2. |
| `justfile` | Setup, tests, bench, and render entry points. |
| `results/` | Committed snapshots from the 2026-11-10 run, plus `pip-freeze.txt`. |
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
just test               # constructor tests; golden type-parity needs the services
just parity             # writes results/type-parity.json
```

The commands that produced the committed snapshots (2026-11-10), against the
older pin, are unchanged. They were not re-run on `7d715a8`:

```bash
# 100k × 5 rounds and 1M × 3 rounds; all backends × all paths.
# Time + memory. The synchronous chart-data stage is in the JSON.
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
`just bench-quick` is a short sanity run (100k rows, 2 rounds).
`just reproduce` runs services, venv, data, tests, parity, both benches, and render.

## Environment

Measured on 2026-11-10 (Asia/Yerevan) on an 8-vCPU `Intel(R) Xeon(R) Processor`
box with 15.6 GiB RAM, Linux 6.12, Python 3.11.17. Other workloads were
running on the same machine, so **absolute times are noisy**; the useful
signal is the comparison across paths in the same run. Versions pinned in
`requirements.txt` and recorded in each JSON snapshot. The Superset commit in
the snapshot is the old pin; the patch in this branch applies to the commit in
`SUPERSET_COMMIT`.

| Component | Version |
|---|---|
| apache/superset (snapshot) | `a131fcb623d88ed9eb7e7a414e226437423d645c` + the patch as of that run |
| apache/superset (this branch) | `7d715a82a69a40389d0f4ce20f0e8ccfb17ce889` + `patches/0001-arrow-native-result-set.patch` |
| pyarrow | 26.0.1 |
| SQLAlchemy | 2.0.57 |
| duckdb / duckdb-engine | 1.5.6 / 0.17.0 |
| psycopg2-binary | 2.9.13 |
| adbc-driver-manager / postgresql / flightsql | 1.13.0 |
| flightsql-dbapi | 0.2.2 (installed with `--no-deps`; it pins SQLAlchemy &lt; 2, which Superset master rejects) |
| Postgres image | `postgres:17.6` |
| Flight SQL image | GizmoSQL 1.42.2 (`sab-flightsql:gizmosql-1.42.2-json`) |

The full `pip freeze` from that run is in [`results/pip-freeze.txt`](results/pip-freeze.txt).
It was not refreshed, because the venv was not reinstalled for a new measurement.

## Results

All numbers below are medians copied from the JSON snapshots. They were not
recomputed on the retargeted patch. The mechanical render is
[`results/BENCH.md`](results/BENCH.md).

### 1,000,000 rows, all paths, IPC

Source: [`results/bench-main.json`](results/bench-main.json), 3 rounds, started
11:34 and finished 12:06 (Asia/Yerevan). `total (IPC)` is the headline
comparison (async SQL Lab default).

| backend | path | fetch (s) | result set (s) | IPC (s) | **total IPC (s)** | speedup vs rows (IPC) | peak RSS (MiB) | tracemalloc (MiB) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | 8.30 | 11.38 | 0.22 | **19.90** | 1.0× | 1884 | 1197 |
| postgres | adbc_rows | 21.78 | 4.50 | 0.23 | **26.51** | 0.8× | 1082 | 870 |
| postgres | arrow | 1.07 | 0.35 | 0.27 | **1.73** | 11.5× | 1010 | 470 |
| duckdb | rows | 7.28 | 5.25 | 0.21 | **12.77** | 1.0× | 1328 | 897 |
| duckdb | adbc_rows | 14.57 | 2.51 | 0.20 | **17.28** | 0.7× | 1203 | 763 |
| duckdb | arrow | 0.22 | &lt;0.001 | 0.17 | **0.40** | 32.0× | 894 | 124 |
| flightsql | rows | 5.97 | 15.26 | 0.20 | **21.46** | 1.0× | 1618 | 1238 |
| flightsql | adbc_rows | 15.30 | 3.16 | 0.20 | **18.64** | 1.2× | 1024 | 763 |
| flightsql | arrow | 0.24 | &lt;0.001 | 0.24 | **0.48** | 44.7× | 697 | 124 |

Arrow is 11.5× / 32.0× / 44.7× faster than the current row path on
Postgres / DuckDB / Flight SQL at this size, measured at `total (IPC)` on that
run. Most of the gain is in fetch (record batches instead of `fetchall()`) and
in result-set construction (`from_arrow` instead of building the result set
from Python rows). `adbc_rows` is usually slower than `rows`: the ADBC driver
still has to convert Arrow to Python rows for today's constructor.

The same run at 100,000 rows (5 rounds) is in the JSON and in
`results/BENCH.md`. Directionally the same: Postgres 1.93 s vs 0.18 s,
DuckDB 1.32 s vs 0.058 s, Flight SQL 2.24 s vs 0.068 s (`total IPC`, rows vs
arrow).

### Arrow only, IPC only: 1M and 3M

`--downstream ipc` stops after `write_ipc_buffer`. That is the async SQL Lab
question, and it is how the Arrow path fits in memory at a few million rows.

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
lower here because the synchronous chart-data conversion is not run
(Postgres 607 MiB vs 1010 MiB at 1M).

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

- **This is a personal prototype, not a Superset PR.** The patch applies to
  the commit in `SUPERSET_COMMIT` and is documented in `patches/README.md`.
  Behaviour can still move if this is proposed upstream later.
- **The snapshot figures are from 2026-11-10**, on the previous pin. They are
  not a measurement of `7d715a8`. If a number from that run no longer describes
  the retargeted code, this README says so instead of guessing. The ADBC
  `fetch_record_batch` → `from_arrow` → IPC sequence that produced `total (IPC)`
  is still the harness's Arrow path.
- **`adbc_rows` is not a proposed feature.** It separates "use an ADBC driver"
  from "use `from_arrow`". It is often slower than the classic row driver.
- **10M was skipped**, as above, to stay under a 5 GiB RSS guard on a 15.6
  GiB box.
- **Shared machine.** Other benches ran concurrently, so treat absolute
  seconds as noisy. Compare paths inside one snapshot.
- **Flight SQL `rows` vs `arrow` are not the same client.** `rows` uses
  `flightsql-dbapi` (the library Superset's DataFusion extra points at) plus
  `DataFusionEngineSpec`. `arrow` / `adbc_rows` use `adbc-driver-flightsql`
  and the sketch `FlightSQLEngineSpec` in the patch. The server is the same
  GizmoSQL process.
- **Type parity is not bit-identical in every column.** Known, pinned
  divergences (integer width, decimal precision metadata, JSON whitespace in
  the IPC payload, interval handling, some Flight SQL date conversions) are
  listed in [`docs/type-parity.md`](docs/type-parity.md) and asserted by
  `just test` when the services are up. Interval is an open gap. Constructor
  tests that do not need services live in `tests/test_from_arrow_unit.py`.
- **UUID stringification is vectorized in the patch** (NumPy, not the
  per-value Python loop in `stringify_extension_columns`). That loop
  dominated the Postgres Arrow result-set stage before the change. A
  snapshot taken before that change is in
  `results/archive/bench-before-vectorized-uuid.json`.

## License

The benchmark code in this repository is provided for reproduction and
discussion. Apache Superset is Apache-2.0 and is not vendored here; it is
cloned at the pinned commit by `just venv`.
