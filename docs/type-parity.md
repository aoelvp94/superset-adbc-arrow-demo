# Type parity: current row path vs Arrow path

Two checks. Neither invents a new result contract; both compare `from_arrow` to the
row constructor that Superset already ships.

**Constructor tests** (`tests/test_from_arrow_unit.py`, no database) build the Python
values the row constructor receives and a `pyarrow.Table` of the same values. They
cover timestamps (naive, UTC, a +05:45 offset, far-future), finite decimals, integers
above 2**63−1, nulls, non-finite floats, dates, nested list/struct values, and column
names. `type_generic` and `is_dttm` are compared for timestamps, floats,
integers, booleans, and dates. Decimal checks compare values: without driver
metadata, `convert_pa_dtype` does not name decimals, and `from_arrow` does not
invent a generic type the row path does not report. Postgres `POSTGRESQL:type`
metadata is what makes the type string match psycopg2.

Two differences are intentional and pinned in those tests:

* A non-finite `Decimal` makes the row constructor stringify the whole column, because
  `pa.array` rejects it. `from_arrow` nulls only the non-finite cells and keeps finite
  values as decimals (the same per-cell rule `stringify_values` states: NaN and
  Infinity have no exact value).
* On `PostgresEngineSpec`, `from_arrow` applies the same milliseconds conversion
  `fetch_data` applies to a timedelta. `month_day_nano_interval` uses psycopg2's
  day counts (a year is 365 days, a month is 30) before `_normalize_interval`.
  A `duration` column is already a timedelta and goes through that function.
  `1 day 02:03:04` is 93784000.0 on both paths. `BaseEngineSpec` and DuckDB do
  not rewrite intervals. The 2026-11-10 live run below still records the old
  divergence; that harness was not re-run.

**Live comparison** below is the 2026-11-10 run. Source of truth:
`results/type-parity.json` (written by `just parity`) and the pinned signature in
`tests/golden/known_divergences.json` (checked by `just test` when the services are
up). This branch retargets the patch and does not re-run that harness. "rows" is the
driver Superset uses today (psycopg2, duckdb-engine, flightsql-dbapi), "adbc_rows" is
an ADBC cursor fed through `fetchall()` + `SupersetResultSet(...)` (diagnostic, not a
proposed feature), "arrow" is an ADBC Arrow fetch + `SupersetResultSet.from_arrow(...)`.
`from_arrow` itself accepts a Table from any source; ADBC is the source that run used.

Compared per column: `pa_table` Arrow type, `.columns` (`type`, `type_generic`, `is_dttm`),
the records of Superset's synchronous chart-data conversion (`to_pandas_df()` +
`df_to_records(..., convert_decimals=True)`), `nested_columns`, and the values in
`pa_table` (what the msgpack/IPC results-backend path ships).

## Benchmark table (1,000 rows; int, float, decimal, text, timestamptz, timestamp, date, bool, json, uuid, nulls)

`type_generic` and `is_dttm` match between rows and arrow for every column on all three
backends (asserted by `test_generic_types_and_dttm_match_on_bench_table`). Sync-path record values
match on Postgres and DuckDB; on Flight SQL they match between adbc_rows and arrow.

| backend | column | rows (today) | arrow (prototype) | impact |
|---|---|---|---|---|
| all | `i32` (INTEGER) | Arrow `int64` | Arrow `int32` | Row path re-infers Python ints as int64; Arrow keeps the server width. Values equal. Deliberately not widened. |
| all | `dec` (DECIMAL(18,4)) | `decimal128(7, 4)` (inferred from values) | Postgres `decimal128(38, 4)`, DuckDB/Flight SQL `decimal128(18, 4)` | Precision metadata only; `Decimal` values equal. |
| postgres | `js` (json) | IPC payload: `json.dumps` of psycopg2's dict -> `{"k": 1, "tag": "x1"}` | IPC payload: server text `{"k" : 1, "tag" : "x1"}` | Whitespace in the IPC/msgpack payload only; sync-path records and `nested_columns` are equal (parsed lazily). |
| flightsql | `d` (DATE) | flightsql-dbapi returns a Timestamp -> Arrow `timestamp[us]` | `date32` -> `datetime.date` | A flightsql-dbapi conversion, not the result set: the ADBC row path already gets `date`. |

## Edge cases (one row each, see `EDGE_COLUMNS` in `bench/parity.py`)

| backend | column | rows (today) | arrow (prototype) | note |
|---|---|---|---|---|
| postgres | `'NaN'::numeric` | NULL (Arrow `null`) | NULL (Arrow `string`, all-null) | `from_arrow` maps NaN/Infinity to NULL like `stringify_values`; an all-NULL column keeps the storage type. |
| postgres | 39-digit numeric | `decimal256(39, 9)` | `decimal256(76, 9)` | Exact value preserved on both. |
| postgres, duckdb | `interval` | Postgres: float milliseconds, 93784000.0 (`column_type_mutators`, applied in `fetch_data` before the row constructor); DuckDB: `duration[us]` | `month_day_nano_interval` in this 2026-11-10 run | **Postgres constructor gap closed since this run.** `PostgresEngineSpec.normalize_arrow_column` now emits the same milliseconds. DuckDB is unchanged. Re-run `just parity` before treating this row as current. |
| postgres | `'5'::json` (scalar) | psycopg2 parses -> `int64` column | JSON text `"5"` (string), not nested | Row path type depends on the JSON content; Arrow keeps the declared type. |
| postgres, duckdb | `NULL::text` / `NULL::VARCHAR` | Arrow `null` | Arrow `string` | DuckDB rows reports type `None`, arrow `STRING`. |
| flightsql | `[1, 2, NULL]` | flightsql-dbapi returns `numpy.ndarray` in `nested_columns` / sync records | Python `list` | an ndarray cell breaks `v == v`-style checks (it broke this harness once). |
| flightsql | `NULL::VARCHAR` | flightsql-dbapi: `double` (`FLOAT`) | `string` (`STRING`) | flightsql-dbapi conversion. |

Matching on all three paths (no divergence recorded): `timestamptz` incl. `+05:45` offsets
(UTC instants equal; Flight SQL zone is `Etc/UTC` on both), far-future `9999-12-31`
timestamps, `bytea`/BLOB, `uuid` (stringified), `int[]`/LIST and STRUCT (stringified JSON +
`nested_columns`), DuckDB ENUM (dictionary decoded to string), `jsonb` objects,
duplicate column names (`dup`, `dup__1`).

## What today's ADBC users get (adbc_rows vs rows), fixed by the patch

Postgres through an ADBC cursor on master (`fetchall()` + current `SupersetResultSet`):

- `numeric` arrives as `arrow.opaque` text -> column type `STRING`, values `str`: no SUM/AVG in Explore. Prototype: `DECIMAL`, `Decimal`.
- `.columns` types fall back to Arrow inference: `INT`, `DATETIME` for `timestamptz` and `date`, `STRING` for `json`/`jsonb`/`int[]`, `None` for `bytea`.
- `interval` is reported as `DATETIME` with `is_dttm=True`.
- `json`/`jsonb` not restored as objects in `nested_columns` (Handlebars charts).

Prototype maps the ADBC `POSTGRESQL:type` field metadata back to the same psycopg2 type names
(`LONGINTEGER`, `DATETIMETZ`, `JSON`, ...), so `.columns` is identical to the psycopg2 path.
