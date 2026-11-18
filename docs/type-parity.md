# Type parity: current row path vs Arrow path

## Summary

`SupersetResultSet.from_arrow(...)` reports the same `type_generic` and `is_dttm` as the
row constructor Superset ships today, for every column on Postgres, DuckDB and Flight SQL.
It also produces the same synchronous chart-data records on Postgres and DuckDB.
Every remaining difference is one of these:

- **Arrow storage details:** integer width, decimal precision, and the type of an
  all-NULL column. Values are equal.
- **Per-cell handling of non-finite decimals:** only the NaN/Infinity cells become NULL,
  instead of the whole column being stringified.
- **Quirks of today's drivers** (psycopg2 JSON scalars, flightsql-dbapi dates and
  arrays), which the Arrow path does not reproduce.

`from_arrow` adds no new result contract. Each difference is pinned in a test and listed
below.

"The patch" below means [`patches/0001-arrow-native-result-set.patch`](../patches/README.md)
applied to apache/superset at the commit in [`SUPERSET_COMMIT`](../SUPERSET_COMMIT).

## The three paths compared

| name | how results are fetched | role |
|---|---|---|
| `rows` | The driver Superset uses today (psycopg2, duckdb-engine, flightsql-dbapi) → `SupersetResultSet(rows, ...)` | Baseline |
| `adbc_rows` | ADBC cursor → `fetchall()` → `SupersetResultSet(rows, ...)` | Diagnostic only. Shows what ADBC users get on master, not a proposed feature |
| `arrow` | ADBC Arrow fetch → `SupersetResultSet.from_arrow(table, ...)` | The patch |

`from_arrow` accepts a `pyarrow.Table` from any source. ADBC is simply the source these
runs used.

**Compared per column**

- `pa_table`: the Arrow type, and the values that the msgpack/IPC results backend ships.
- `.columns`: `type`, `type_generic`, `is_dttm`.
- Sync chart-data records: `to_pandas_df()` + `df_to_records(..., convert_decimals=True)`.
- `nested_columns`.

## Unit tests (no database)

`tests/test_from_arrow_unit.py` builds two inputs with the same values: the Python rows the
row constructor receives, and a `pyarrow.Table`. It covers:

- timestamps: naive, UTC, a `+05:45` offset, far-future
- finite decimals and integers above 2**63−1
- nulls, non-finite floats, dates
- nested list/struct values
- column names

For timestamps, floats, integers, booleans and dates, the tests compare `type_generic`
and `is_dttm`. Decimals are compared by value only: without driver metadata neither path
assigns them a generic type. On Postgres, the ADBC `POSTGRESQL:type` field metadata is
what makes the `type` string match psycopg2.

### Intentional differences

Each one is pinned in the unit tests. `tests/test_from_arrow_parity_matrix.py` also covers
the all-NULL case.

1. **Non-finite `Decimal`.** `pa.array` rejects NaN/Infinity decimals, so the row path
   stringifies the whole column. `from_arrow` sets only the non-finite cells to NULL and
   keeps the finite values as `Decimal`. This applies per cell the rule `stringify_values`
   already follows: NaN and Infinity have no exact value.
2. **All-NULL column.** `from_arrow` keeps the declared Arrow type (`double`, `string`,
   `timestamp[us, tz=UTC]`, ...). The row path builds an Arrow `null` column.
   `type_generic` and records are equal. The pandas dtype differs
   (`float64` / `str` / `datetime64` vs `object`).
3. **`int32` width.** `from_arrow` keeps `int32`, while the row path re-infers `int64`.
   Values and records are equal. Deliberately not widened.
4. **Postgres intervals.** On `PostgresEngineSpec`, `from_arrow` converts intervals to
   float milliseconds, as `fetch_data` already does for a `timedelta`:
   - `month_day_nano_interval` is first turned into a `timedelta` using psycopg2's
     convention (1 month = 30 days, 1 year = 365 days), then passed to
     `_normalize_interval`. Like psycopg2, this is approximate for month/year intervals.
   - `duration` is already a `timedelta` and goes straight to `_normalize_interval`.
   - Example: `1 day 02:03:04` → `93784000.0` on both paths (confirmed live, below).
   - `BaseEngineSpec` and DuckDB leave intervals unchanged on both paths.

## Live comparison

Run on 2026-11-14 against apache/superset `f81191d` (the pin in `SUPERSET_COMMIT`) plus
the patch.

- **Source of truth:** `results/type-parity.json`, written by `just parity`.
- **Regression guard:** `tests/golden/known_divergences.json`, checked by `just test`
  when the services are up.

### Bench table (1,000 rows)

Columns: int, float, decimal, text, timestamptz, timestamp, date, bool, json, uuid, nulls.

- `type_generic` and `is_dttm` match between `rows` and `arrow` for every column on all
  three backends (`test_generic_types_and_dttm_match_on_bench_table`).
- Sync records match between `rows` and `arrow` on Postgres and DuckDB.
- On Flight SQL, `rows` differs from `arrow` only because of flightsql-dbapi's date
  handling (see `d` below). `adbc_rows` and `arrow` match.

| backend | column | `rows` (today) | `arrow` (patch) | impact |
|---|---|---|---|---|
| all | `i32` (INTEGER) | `int64` | `int32` | Width only. Values equal. |
| all | `dec` (DECIMAL(18,4)) | `decimal128(7, 4)` (inferred from values) | Postgres `decimal128(38, 4)`; DuckDB / Flight SQL `decimal128(18, 4)` | Precision metadata only. `Decimal` values equal. |
| postgres | `js` (json) | IPC payload: `json.dumps` of psycopg2's dict → `{"k": 1, "tag": "x1"}` | IPC payload: server text `{"k" : 1, "tag" : "x1"}` | Whitespace in the IPC/msgpack payload only. Sync records and `nested_columns` are equal. |
| flightsql | `d` (DATE) | flightsql-dbapi returns a Timestamp → `timestamp[us]` | `date32` → `datetime.date` | A flightsql-dbapi conversion. `adbc_rows` already gets `date`. |

### Edge cases

One row each, defined in `EDGE_COLUMNS` in `bench/parity.py`.

| backend | column | `rows` (today) | `arrow` (patch) | note |
|---|---|---|---|---|
| postgres | `'NaN'::numeric` | NULL, Arrow `null` | NULL, Arrow `string` (all-null) | Differences 1 + 2 combined. Row path: column stringified, then NaN → NULL, so the column is all-null and typed `null`. Arrow path: NaN cell → NULL, and the column keeps its ADBC storage type (`arrow.opaque` numeric text, so `string`). |
| postgres | 39-digit numeric | `decimal256(39, 9)` | `decimal256(76, 9)` | Exact value preserved on both. |
| postgres | `interval` | float ms (`93784000.0`), `INTERVAL` / `NUMERIC` | same | Difference 4. `adbc_rows` gets a pandas `DateOffset` instead. |
| duckdb | `interval` | `duration[us]` | `month_day_nano_interval` | Not rewritten on either path. |
| postgres | `'5'::json` (scalar) | psycopg2 parses it → `int64` column | JSON text `"5"` (`string`), not nested | The row-path type depends on JSON content. Arrow keeps the declared type. |
| postgres, duckdb | `NULL::text` / `NULL::VARCHAR` | Arrow `null` (DuckDB `type`: `None`) | Arrow `string` (`STRING`) | Difference 2. |
| flightsql | `NULL::VARCHAR` | `double` (`FLOAT`) | `string` (`STRING`) | flightsql-dbapi conversion. |
| flightsql | `[1, 2, NULL]` | `numpy.ndarray` in `nested_columns` and sync records | Python `list` | An ndarray cell breaks `v == v`-style checks. |

**No divergence on any path:**

- `timestamptz`, including `+05:45` offsets (same UTC instants; Flight SQL zone is
  `Etc/UTC` on both)
- far-future `9999-12-31` timestamps
- `bytea` / BLOB
- `uuid` (stringified)
- `int[]` / LIST and STRUCT (stringified JSON + `nested_columns`)
- DuckDB ENUM (dictionary decoded to string)
- `jsonb` objects
- duplicate column names (`dup`, `dup__1`)

## What ADBC users get today, and what the patch fixes

On master, a Postgres ADBC cursor (`adbc_rows`) loses type information:

| issue on master (`adbc_rows`) | with the patch (`arrow`) |
|---|---|
| `numeric` arrives as `arrow.opaque` text → type `STRING`, values `str`, so no SUM/AVG in Explore | `DECIMAL`, `Decimal` values |
| `.columns` falls back to Arrow inference: `INT`; `DATETIME` for both `timestamptz` and `date`; `STRING` for `json`/`jsonb`/`int[]`; `None` for `bytea` | Same type names as psycopg2 (`LONGINTEGER`, `DATETIMETZ`, `JSON`, ...) |
| `interval` reported as `DATETIME` with `is_dttm=True` | Float milliseconds, `is_dttm=False` |
| `json`/`jsonb` not restored as objects in `nested_columns` (breaks Handlebars charts) | Restored |

The patch reads the ADBC `POSTGRESQL:type` field metadata and maps it back to psycopg2's
type names, so `.columns` matches the psycopg2 path exactly.
