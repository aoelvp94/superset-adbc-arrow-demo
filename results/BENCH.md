# Benchmark results

Snapshot: `results/bench-main.json` (started 2026-11-10T07:34:47.217714+00:00, finished 2026-11-10T08:06:20.388875+00:00).
All numbers below are copied from that JSON by `bench/render.py`; medians over the rounds shown.

Times in seconds (wall clock). `total (IPC)` = fetch + result set + `write_ipc_buffer` (SQL Lab with `RESULTS_BACKEND_USE_MSGPACK=True`, the default). `total (pandas)` = fetch + result set + `to_pandas_df()`. Peak RSS is the resident-memory high-water mark above the RSS just before the query (VmHWM reset). tracemalloc peak counts Python-heap allocations only (Arrow/ADBC C buffers are not traced) and comes from a separate run.

## 100,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | psycopg2 | 5 | 0.664 | 1.236 | 0.019 | 0.034 | **1.926** | 1.940 | 1.0x | 212 | 120 |
| postgres | adbc_rows | adbc-driver-postgresql | 5 | 2.015 | 0.585 | 0.020 | 0.015 | **2.621** | 2.615 | 0.7x | 126 | 87 |
| postgres | arrow | adbc-driver-postgresql | 5 | 0.114 | 0.045 | 0.019 | 0.150 | **0.179** | 0.310 | 10.8x | 122 | 49 |
| duckdb | rows | duckdb-engine | 5 | 0.639 | 0.642 | 0.020 | 0.037 | **1.321** | 1.337 | 1.0x | 150 | 90 |
| duckdb | adbc_rows | adbc_driver_duckdb | 5 | 1.467 | 0.218 | 0.021 | 0.032 | **1.702** | 1.713 | 0.8x | 131 | 76 |
| duckdb | arrow | adbc_driver_duckdb | 5 | 0.038 | <0.001 | 0.024 | 0.039 | **0.058** | 0.079 | 22.6x | 100 | 15 |
| flightsql | rows | flightsql-dbapi | 5 | 0.669 | 1.557 | 0.020 | 0.024 | **2.237** | 2.242 | 1.0x | 180 | 126 |
| flightsql | adbc_rows | adbc-driver-flightsql | 5 | 1.482 | 0.295 | 0.021 | 0.033 | **1.808** | 1.821 | 1.2x | 124 | 76 |
| flightsql | arrow | adbc-driver-flightsql | 5 | 0.050 | <0.001 | 0.020 | 0.036 | **0.068** | 0.096 | 32.9x | 82 | 15 |

## 1,000,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | psycopg2 | 3 | 8.304 | 11.4 | 0.216 | 0.267 | **19.9** | 19.9 | 1.0x | 1,884 | 1,197 |
| postgres | adbc_rows | adbc-driver-postgresql | 3 | 21.8 | 4.499 | 0.229 | 0.063 | **26.5** | 26.3 | 0.8x | 1,082 | 870 |
| postgres | arrow | adbc-driver-postgresql | 3 | 1.072 | 0.355 | 0.275 | 1.572 | **1.727** | 2.979 | 11.5x | 1,010 | 470 |
| duckdb | rows | duckdb-engine | 3 | 7.275 | 5.255 | 0.215 | 0.266 | **12.8** | 12.8 | 1.0x | 1,328 | 897 |
| duckdb | adbc_rows | adbc_driver_duckdb | 3 | 14.6 | 2.514 | 0.201 | 0.274 | **17.3** | 17.4 | 0.7x | 1,203 | 763 |
| duckdb | arrow | adbc_driver_duckdb | 3 | 0.225 | <0.001 | 0.174 | 0.268 | **0.399** | 0.493 | 32.0x | 894 | 124 |
| flightsql | rows | flightsql-dbapi | 3 | 5.973 | 15.3 | 0.205 | 0.256 | **21.5** | 21.5 | 1.0x | 1,618 | 1,238 |
| flightsql | adbc_rows | adbc-driver-flightsql | 3 | 15.3 | 3.160 | 0.201 | 0.294 | **18.6** | 18.7 | 1.2x | 1,024 | 763 |
| flightsql | arrow | adbc-driver-flightsql | 3 | 0.244 | <0.001 | 0.236 | 0.277 | **0.480** | 0.524 | 44.7x | 697 | 124 |

## Environment

```json
{
 "python": "3.11.17",
 "platform": "Linux-6.12.113+-x86_64-with-glibc2.41",
 "apache-superset": "0.0.0.dev0",
 "pyarrow": "26.0.1",
 "pandas": "3.1.1",
 "numpy": "2.4.6",
 "sqlalchemy": "2.0.57",
 "duckdb": "1.5.6",
 "duckdb-engine": "0.17.0",
 "psycopg2-binary": "2.9.13",
 "adbc-driver-manager": "1.13.0",
 "adbc-driver-postgresql": "1.13.0",
 "adbc-driver-flightsql": "1.13.0",
 "flightsql-dbapi": "0.2.2",
 "superset_commit": "a131fcb623d88ed9eb7e7a414e226437423d645c",
 "cpu": "Intel(R) Xeon(R) Processor",
 "cpu_count": 8,
 "mem_total_gb": 15.6,
 "docker_images": [
  "/sab-postgres postgres:17.6 sha256:50903ccdcab597707a1f61c7ae016a06b0b548da53a6f7ad716d56b072bedba0",
  "/sab-flightsql sab-flightsql:gizmosql-1.42.2-json sha256:904b5882e073441855f7a51212819bba1791b00cfaa8950f36de2af08a0cc015"
 ]
}
```

# Additional run: results/bench-large-ipc.json

Downstream: **IPC only** (`--downstream ipc`): Superset's `to_pandas_df()` is not run, so `pandas` / `total (pandas)` are `-`.

Snapshot: `results/bench-large-ipc.json` (started 2026-11-10T08:06:20.446885+00:00, finished 2026-11-10T08:07:24.969247+00:00).
All numbers below are copied from that JSON by `bench/render.py`; medians over the rounds shown.

Times in seconds (wall clock). `total (IPC)` = fetch + result set + `write_ipc_buffer` (SQL Lab with `RESULTS_BACKEND_USE_MSGPACK=True`, the default). `total (pandas)` = fetch + result set + `to_pandas_df()`. Peak RSS is the resident-memory high-water mark above the RSS just before the query (VmHWM reset). tracemalloc peak counts Python-heap allocations only (Arrow/ADBC C buffers are not traced) and comes from a separate run.

## 1,000,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | arrow | adbc-driver-postgresql | 3 | 1.172 | 0.345 | 0.257 | - | **1.757** | - | n/a (rows path skipped) | 607 | 11 |
| duckdb | arrow | adbc_driver_duckdb | 3 | 0.291 | <0.001 | 0.168 | - | **0.468** | - | n/a (rows path skipped) | 743 | 0 |
| flightsql | arrow | adbc-driver-flightsql | 3 | 0.257 | <0.001 | 0.242 | - | **0.500** | - | n/a (rows path skipped) | 546 | 0 |

## Skipped

- postgres/arrow at 10,000,000 rows: estimated peak RSS 5.9 GiB > --max-rss-gb 5.0
- duckdb/arrow at 10,000,000 rows: estimated peak RSS 7.3 GiB > --max-rss-gb 5.0
- flightsql/arrow at 10,000,000 rows: estimated peak RSS 5.3 GiB > --max-rss-gb 5.0

## Environment

```json
{
 "python": "3.11.17",
 "platform": "Linux-6.12.113+-x86_64-with-glibc2.41",
 "apache-superset": "0.0.0.dev0",
 "pyarrow": "26.0.1",
 "pandas": "3.1.1",
 "numpy": "2.4.6",
 "sqlalchemy": "2.0.57",
 "duckdb": "1.5.6",
 "duckdb-engine": "0.17.0",
 "psycopg2-binary": "2.9.13",
 "adbc-driver-manager": "1.13.0",
 "adbc-driver-postgresql": "1.13.0",
 "adbc-driver-flightsql": "1.13.0",
 "flightsql-dbapi": "0.2.2",
 "superset_commit": "a131fcb623d88ed9eb7e7a414e226437423d645c",
 "cpu": "Intel(R) Xeon(R) Processor",
 "cpu_count": 8,
 "mem_total_gb": 15.6,
 "docker_images": [
  "/sab-postgres postgres:17.6 sha256:50903ccdcab597707a1f61c7ae016a06b0b548da53a6f7ad716d56b072bedba0",
  "/sab-flightsql sab-flightsql:gizmosql-1.42.2-json sha256:904b5882e073441855f7a51212819bba1791b00cfaa8950f36de2af08a0cc015"
 ]
}
```

# Additional run: results/bench-large-ipc-3m.json

Downstream: **IPC only** (`--downstream ipc`): Superset's `to_pandas_df()` is not run, so `pandas` / `total (pandas)` are `-`.

Snapshot: `results/bench-large-ipc-3m.json` (started 2026-11-10T08:10:45.568198+00:00, finished 2026-11-10T08:12:13.709933+00:00).
All numbers below are copied from that JSON by `bench/render.py`; medians over the rounds shown.

Times in seconds (wall clock). `total (IPC)` = fetch + result set + `write_ipc_buffer` (SQL Lab with `RESULTS_BACKEND_USE_MSGPACK=True`, the default). `total (pandas)` = fetch + result set + `to_pandas_df()`. Peak RSS is the resident-memory high-water mark above the RSS just before the query (VmHWM reset). tracemalloc peak counts Python-heap allocations only (Arrow/ADBC C buffers are not traced) and comes from a separate run.

## 3,000,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | arrow | adbc-driver-postgresql | 3 | 3.327 | 1.095 | 0.533 | - | **4.855** | - | n/a (rows path skipped) | 1,219 | 11 |
| duckdb | arrow | adbc_driver_duckdb | 3 | 0.786 | <0.001 | 0.510 | - | **1.380** | - | n/a (rows path skipped) | 1,906 | 0 |
| flightsql | arrow | adbc-driver-flightsql | 3 | 0.629 | <0.001 | 0.518 | - | **1.119** | - | n/a (rows path skipped) | 1,347 | 0 |

## Environment

```json
{
 "python": "3.11.17",
 "platform": "Linux-6.12.113+-x86_64-with-glibc2.41",
 "apache-superset": "0.0.0.dev0",
 "pyarrow": "26.0.1",
 "pandas": "3.1.1",
 "numpy": "2.4.6",
 "sqlalchemy": "2.0.57",
 "duckdb": "1.5.6",
 "duckdb-engine": "0.17.0",
 "psycopg2-binary": "2.9.13",
 "adbc-driver-manager": "1.13.0",
 "adbc-driver-postgresql": "1.13.0",
 "adbc-driver-flightsql": "1.13.0",
 "flightsql-dbapi": "0.2.2",
 "superset_commit": "a131fcb623d88ed9eb7e7a414e226437423d645c",
 "cpu": "Intel(R) Xeon(R) Processor",
 "cpu_count": 8,
 "mem_total_gb": 15.6,
 "docker_images": [
  "/sab-postgres postgres:17.6 sha256:50903ccdcab597707a1f61c7ae016a06b0b548da53a6f7ad716d56b072bedba0",
  "/sab-flightsql sab-flightsql:gizmosql-1.42.2-json sha256:904b5882e073441855f7a51212819bba1791b00cfaa8950f36de2af08a0cc015"
 ]
}
```
