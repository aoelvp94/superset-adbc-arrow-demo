# patches/0001-arrow-native-result-set.patch

Local prototype against apache/superset master `a131fcb623d88ed9eb7e7a414e226437423d645c`
(see `../SUPERSET_COMMIT`). Not submitted anywhere. Apply with:

```bash
git -C <superset checkout at that commit> apply --index patches/0001-arrow-native-result-set.patch
```

`just venv` does this automatically in `.cache/superset` and installs the result.

| file | change |
|---|---|
| `superset/result_set.py` | `SupersetResultSet.from_arrow(table, db_engine_spec)`: builds the result set from a `pa.Table` with no Python rows. Same column-name normalization/dedup; decodes dictionaries; PostgreSQL `arrow.opaque` NUMERIC -> `decimal128(38, s)` / `decimal256(76, s)` with NaN/Infinity -> NULL (as `stringify_values` does); `arrow.json` kept as text with parsed objects exposed lazily through `nested_columns` / `to_pandas_df()` (the IPC path never parses JSON); nested Arrow types stringified + kept in `nested_columns` like the row path; `arrow.uuid` stringified vectorized with NumPy (the existing `stringify_extension_columns` loops in Python and cost 3.07 s per 1M PostgreSQL uuids in a one-off timing on this box); other extension types still go through `stringify_extension_columns`. The row constructor is unchanged. |
| `superset/db_engine_specs/base.py` | `supports_arrow_fetch = False` (opt-in), `fetch_arrow(cursor, limit)` using `cursor.fetch_record_batch()` and stopping after `limit` rows, `get_datatype_from_arrow_field(field)` (reads `<VENDOR>:type` field metadata). Returns `None` for cursors without Arrow fetch, so psycopg2/duckdb-engine keep the row path. |
| `superset/db_engine_specs/postgres.py` | opt in; maps ADBC `POSTGRESQL:type` names to built-in OIDs and reuses `get_datatype(oid)`, so `.columns` types match the psycopg2 row path exactly. |
| `superset/db_engine_specs/duckdb.py` | opt in. |
| `superset/db_engine_specs/flightsql.py` | **sketch** of a generic "Arrow Flight SQL (ADBC)" engine spec (`flightsql+adbc://`, via `sqlalchemy-adbc`), modeled on `datafusion.py` / `dremio.py`, ANSI `DATE_TRUNC` grains. |
| `superset/sql_lab.py` | `_execute_query`: when feature flag `ARROW_NATIVE_RESULT_SET` is on and `fetch_arrow` returns a table, apply the limit on the table and return `SupersetResultSet.from_arrow(...)`; otherwise the existing `fetch_data` path. |
| `superset/config.py` | `ARROW_NATIVE_RESULT_SET: False` feature flag (`@lifecycle: development`). |
| `pyproject.toml` | `flightsql` extra: `sqlalchemy-adbc[flightsql]>=0.9.5,<1; python_version >= '3.12'` (marker because sqlalchemy-adbc requires Python 3.12). |
| `tests/unit_tests/result_set_from_arrow_test.py` | upstream-style unit tests for the above. |

Deliberately out of scope: chart-data / Arrow-over-the-wire (draft apache/superset#45363),
`fetch_data` callers other than SQL Lab (`models/core.py`, `connectors/sqla/utils.py`,
`sql/execution/executor.py`), interval normalization, reflection fixes in sqlalchemy-adbc.
