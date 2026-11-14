# Benchmark results

Snapshot: `results/bench-main.json` (started 2026-11-14T15:04:17.968514+00:00, finished 2026-11-14T15:42:30.633565+00:00).
All numbers below are copied from that JSON by `bench/render.py`; medians over the rounds shown.

Times in seconds (wall clock). `total (IPC)` = fetch + result set + `write_ipc_buffer` (SQL Lab with `RESULTS_BACKEND_USE_MSGPACK=True`, the default). `total (pandas)` = fetch + result set + `to_pandas_df()`. Peak RSS is the resident-memory high-water mark above the RSS just before the query. On this platform the high-water mark cannot be reset, so it also covers imports and setup in the worker process; compare it across paths only. tracemalloc peak counts Python-heap allocations only (Arrow/ADBC C buffers are not traced) and comes from a separate run.

## 10,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | psycopg2 | 5 | 0.042 | 0.079 | <0.001 | 0.004 | **0.130** | 0.141 | 1.0x | 21 | 13 |
| postgres | adbc_rows | adbc-driver-postgresql | 5 | 0.192 | 0.034 | <0.001 | 0.003 | **0.218** | 0.219 | 0.6x | 13 | 9 |
| postgres | arrow | adbc-driver-postgresql | 5 | 0.021 | 0.004 | <0.001 | 0.011 | **0.026** | 0.037 | 5.0x | 11 | 5 |
| duckdb | rows | duckdb-engine | 5 | 0.040 | 0.041 | <0.001 | 0.003 | **0.077** | 0.078 | 1.0x | 16 | 9 |
| duckdb | adbc_rows | adbc_driver_duckdb | 5 | 0.118 | 0.016 | <0.001 | 0.002 | **0.135** | 0.136 | 0.6x | 16 | 8 |
| duckdb | arrow | adbc_driver_duckdb | 5 | 0.003 | <0.001 | <0.001 | 0.003 | **0.005** | 0.007 | 16.7x | 12 | 2 |
| flightsql | rows | flightsql-dbapi | 5 | 0.070 | 0.112 | <0.001 | 0.002 | **0.183** | 0.184 | 1.0x | 17 | 13 |
| flightsql | adbc_rows | adbc-driver-flightsql | 5 | 0.133 | 0.020 | <0.001 | 0.002 | **0.154** | 0.156 | 1.2x | 18 | 8 |
| flightsql | arrow | adbc-driver-flightsql | 5 | 0.037 | <0.001 | <0.001 | 0.007 | **0.038** | 0.044 | 4.7x | 14 | 2 |

## 50,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | psycopg2 | 5 | 0.173 | 0.370 | 0.002 | 0.008 | **0.552** | 0.558 | 1.0x | 96 | 60 |
| postgres | adbc_rows | adbc-driver-postgresql | 5 | 0.681 | 0.210 | 0.002 | 0.002 | **0.893** | 0.894 | 0.6x | 52 | 43 |
| postgres | arrow | adbc-driver-postgresql | 5 | 0.090 | 0.011 | 0.002 | 0.044 | **0.102** | 0.153 | 5.4x | 50 | 25 |
| duckdb | rows | duckdb-engine | 5 | 0.128 | 0.233 | 0.002 | 0.007 | **0.364** | 0.369 | 1.0x | 59 | 45 |
| duckdb | adbc_rows | adbc_driver_duckdb | 5 | 0.476 | 0.076 | 0.002 | 0.011 | **0.567** | 0.576 | 0.6x | 51 | 38 |
| duckdb | arrow | adbc_driver_duckdb | 5 | 0.009 | <0.001 | 0.002 | 0.010 | **0.012** | 0.020 | 30.9x | 41 | 7 |
| flightsql | rows | flightsql-dbapi | 5 | 0.239 | 0.401 | 0.002 | 0.006 | **0.653** | 0.657 | 1.0x | 81 | 63 |
| flightsql | adbc_rows | adbc-driver-flightsql | 5 | 0.581 | 0.091 | 0.002 | 0.007 | **0.681** | 0.687 | 1.0x | 57 | 38 |
| flightsql | arrow | adbc-driver-flightsql | 5 | 0.084 | <0.001 | 0.002 | 0.009 | **0.087** | 0.094 | 7.5x | 37 | 7 |

## 100,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | psycopg2 | 5 | 0.452 | 0.645 | 0.004 | 0.019 | **1.101** | 1.117 | 1.0x | 188 | 120 |
| postgres | adbc_rows | adbc-driver-postgresql | 5 | 1.250 | 0.309 | 0.003 | 0.005 | **1.562** | 1.564 | 0.7x | 103 | 87 |
| postgres | arrow | adbc-driver-postgresql | 5 | 0.136 | 0.017 | 0.005 | 0.088 | **0.175** | 0.259 | 6.3x | 100 | 49 |
| duckdb | rows | duckdb-engine | 5 | 0.314 | 0.344 | 0.003 | 0.013 | **0.657** | 0.667 | 1.0x | 119 | 90 |
| duckdb | adbc_rows | adbc_driver_duckdb | 5 | 0.822 | 0.128 | 0.003 | 0.014 | **0.957** | 0.968 | 0.7x | 103 | 76 |
| duckdb | arrow | adbc_driver_duckdb | 5 | 0.014 | <0.001 | 0.005 | 0.016 | **0.020** | 0.032 | 32.7x | 82 | 15 |
| flightsql | rows | flightsql-dbapi | 5 | 0.414 | 0.858 | 0.003 | 0.012 | **1.268** | 1.277 | 1.0x | 159 | 126 |
| flightsql | adbc_rows | adbc-driver-flightsql | 5 | 0.847 | 0.165 | 0.003 | 0.013 | **1.018** | 1.029 | 1.2x | 102 | 76 |
| flightsql | arrow | adbc-driver-flightsql | 5 | 0.107 | <0.001 | 0.005 | 0.017 | **0.114** | 0.123 | 11.1x | 73 | 15 |

## 1,000,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | rows | psycopg2 | 3 | 4.427 | 8.866 | 0.111 | 0.148 | **13.4** | 13.4 | 1.0x | 1,602 | 1,197 |
| postgres | adbc_rows | adbc-driver-postgresql | 3 | 12.4 | 2.454 | 0.041 | 0.026 | **14.8** | 14.8 | 0.9x | 959 | 870 |
| postgres | arrow | adbc-driver-postgresql | 3 | 0.954 | 0.154 | 0.101 | 0.889 | **1.251** | 2.019 | 10.7x | 837 | 470 |
| duckdb | rows | duckdb-engine | 3 | 3.119 | 2.671 | 0.036 | 0.105 | **5.826** | 5.895 | 1.0x | 1,148 | 897 |
| duckdb | adbc_rows | adbc_driver_duckdb | 3 | 9.466 | 1.611 | 0.030 | 0.105 | **11.1** | 11.2 | 0.5x | 861 | 763 |
| duckdb | arrow | adbc_driver_duckdb | 3 | 0.125 | <0.001 | 0.085 | 0.125 | **0.217** | 0.265 | 26.8x | 793 | 124 |
| flightsql | rows | flightsql-dbapi | 3 | 3.168 | 7.858 | 0.038 | 0.103 | **11.1** | 11.2 | 1.0x | 1,438 | 1,238 |
| flightsql | adbc_rows | adbc-driver-flightsql | 3 | 7.803 | 1.754 | 0.029 | 0.101 | **9.600** | 9.672 | 1.2x | 893 | 763 |
| flightsql | arrow | adbc-driver-flightsql | 3 | 0.496 | <0.001 | 0.096 | 0.123 | **0.592** | 0.620 | 18.7x | 698 | 124 |

## Environment

```json
{
 "python": "3.11.14",
 "platform": "darwin",
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
 "superset_commit": "f81191d55eef3e0fa3ae04b1c83d4e474a2a392a",
 "cpu": "Apple M4",
 "cpu_count": 10,
 "mem_total_gb": 24.0,
 "docker_images": [
  "/sab-postgres postgres:17.6 sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929",
  "/sab-flightsql sab-flightsql:gizmosql-1.42.2-json sha256:4e6aff9f3038c93e4e611c4745c7992abddcfbfc06a87f12acc2178e8eda8dea"
 ]
}
```

# Additional run: results/bench-large-ipc.json

Downstream: **IPC only** (`--downstream ipc`): Superset's `to_pandas_df()` is not run, so `pandas` / `total (pandas)` are `-`.

Snapshot: `results/bench-large-ipc.json` (started 2026-11-14T15:42:30.772909+00:00, finished 2026-11-14T15:44:09.370655+00:00).
All numbers below are copied from that JSON by `bench/render.py`; medians over the rounds shown.

Times in seconds (wall clock). `total (IPC)` = fetch + result set + `write_ipc_buffer` (SQL Lab with `RESULTS_BACKEND_USE_MSGPACK=True`, the default). `total (pandas)` = fetch + result set + `to_pandas_df()`. Peak RSS is the resident-memory high-water mark above the RSS just before the query. On this platform the high-water mark cannot be reset, so it also covers imports and setup in the worker process; compare it across paths only. tracemalloc peak counts Python-heap allocations only (Arrow/ADBC C buffers are not traced) and comes from a separate run.

## 1,000,000 rows

| backend | path | driver | rounds | fetch | result set | IPC | pandas | total (IPC) | total (pandas) | speedup vs rows (IPC) | peak RSS MiB | tracemalloc MiB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | arrow | adbc-driver-postgresql | 3 | 1.028 | 0.188 | 0.141 | - | **1.277** | - | n/a (rows path skipped) | 590 | 11 |
| duckdb | arrow | adbc_driver_duckdb | 3 | 0.143 | <0.001 | 0.097 | - | **0.244** | - | n/a (rows path skipped) | 730 | 0 |
| flightsql | arrow | adbc-driver-flightsql | 3 | 0.946 | <0.001 | 0.134 | - | **1.060** | - | n/a (rows path skipped) | 544 | 0 |

## Skipped

- postgres/arrow at 10,000,000 rows: estimated peak RSS 5.8 GiB > --max-rss-gb 5.0
- duckdb/arrow at 10,000,000 rows: estimated peak RSS 7.1 GiB > --max-rss-gb 5.0
- flightsql/arrow at 10,000,000 rows: estimated peak RSS 5.3 GiB > --max-rss-gb 5.0

## Environment

```json
{
 "python": "3.11.14",
 "platform": "darwin",
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
 "superset_commit": "f81191d55eef3e0fa3ae04b1c83d4e474a2a392a",
 "cpu": "Apple M4",
 "cpu_count": 10,
 "mem_total_gb": 24.0,
 "docker_images": [
  "/sab-postgres postgres:17.6 sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929",
  "/sab-flightsql sab-flightsql:gizmosql-1.42.2-json sha256:4e6aff9f3038c93e4e611c4745c7992abddcfbfc06a87f12acc2178e8eda8dea"
 ]
}
```
