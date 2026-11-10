# Type parity: current row path vs Arrow path

Source of truth: `results/type-parity.json` (written by `just parity`) and the pinned
signature in `tests/golden/known_divergences.json` (checked by `just test`). Everything
below was observed in those files. "rows" is the driver Superset uses today (psycopg2,
duckdb-engine, flightsql-dbapi), "adbc_rows" is an ADBC cursor fed through today's
`fetchall()` + `SupersetResultSet(...)` (what a `sqlalchemy-adbc` user gets on master),
"arrow" is ADBC `fetch_record_batch()` + the prototype `SupersetResultSet.from_arrow(...)`.

Compared per column: `pa_table` Arrow type, `.columns` (`type`, `type_generic`, `is_dttm`,
what SQL Lab and Explore use), the records of Superset's sync path (Superset's own
`to_pandas_df()` + `df_to_records(..., convert_decimals=True)`, as in
`sql_lab._serialize_and_expand_data`), `nested_columns`, and the values in `pa_table` (what
the msgpack/IPC results-backend path ships). The harness itself does not use pandas.

## Benchmark table (1,000 rows; int, float, decimal, text, timestamptz, timestamp, date, bool, json, uuid, nulls)

`type_generic` and `is_dttm` match between rows and arrow for every column on all three
backends (asserted by `test_generic_types_and_dttm_match_on_bench_table`). Sync-path record values
match on Postgres and DuckDB; on Flight SQL they match between adbc_rows and arrow.

| backend | column | rows (today) | arrow (prototype) | impact |
|---|---|---|---|---|
| all | `i32` (INTEGER) | Arrow `int64` | Arrow `int32` | Row path re-infers Python ints as int64; Arrow keeps the server width. Values equal. Deliberately not widened. |
| all | `dec` (DECIMAL(18,4)) | `decimal128(7, 4)` (inferred from values) | Postgres `decimal128(38, 4)`, DuckDB/Flight SQL `decimal128(18, 4)` | Precision metadata only; `Decimal` values equal. |
| postgres | `js` (json) | IPC payload: `json.dumps` of psycopg2's dict -> `{"k": 1, "tag": "x1"}` | IPC payload: server text `{"k" : 1, "tag" : "x1"}` | Whitespace in the IPC/msgpack payload only; sync-path records and `nested_columns` are equal (parsed lazily). |
| flightsql | `d` (DATE) | flightsql-dbapi returns `pandas.Timestamp` -> Arrow `timestamp[us]` | `date32` -> `datetime.date` | A flightsql-dbapi conversion, not the result set: the ADBC row path already gets `date`. |

## Edge cases (one row each, see `EDGE_COLUMNS` in `bench/parity.py`)

| backend | column | rows (today) | arrow (prototype) | note |
|---|---|---|---|---|
| postgres | `'NaN'::numeric` | NULL (Arrow `null`) | NULL (Arrow `string`, all-null) | `from_arrow` maps NaN/Infinity to NULL like `stringify_values`; an all-NULL column keeps the storage type. |
| postgres | 39-digit numeric | `decimal256(39, 9)` | `decimal256(76, 9)` | Exact value preserved on both. |
| postgres, duckdb | `interval` | Postgres: float milliseconds, 93784000.0 (`column_type_mutators`); DuckDB: `duration[us]` (a pandas `Timedelta` after Superset's `to_pandas_df()`) | `month_day_nano_interval`; Superset's `to_pandas_df()` turns it into a pandas `DateOffset` object | **Open.** Needs an engine-spec hook (Postgres) or a cast when months == 0. Not handled by the prototype. |
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
