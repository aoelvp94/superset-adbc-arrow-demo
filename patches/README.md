# patches/0001-arrow-native-result-set.patch

Local prototype against apache/superset master `14365bbebd3ecfb3d9a0c1304908248d5fbeb3d4`
(see `../SUPERSET_COMMIT`; master as of 2026-11-11). Not submitted upstream. Apply with:

```bash
git -C <superset checkout at that commit> apply --index patches/0001-arrow-native-result-set.patch
```

`just venv` does this in `.cache/superset` and installs the result.

The previous snapshot (2026-11-10) was taken against `a131fcb623d88ed9eb7e7a414e226437423d645c`.
An intermediate pin, `7d715a82a69a40389d0f4ce20f0e8ccfb17ce889`, touched none of
the files in this patch. The numbers in `results/` were not re-run after either move.

| file | change |
|---|---|
| `superset/result_set.py` | `SupersetResultSet.from_arrow(table, db_engine_spec)` builds a result set from any `pyarrow.Table`. It does not fetch and does not require ADBC. Same column-name normalization and dedup as the row constructor; dictionary columns decoded; `arrow.opaque` NUMERIC becomes `decimal128` / `decimal256` with NaN/Infinity mapped to NULL; `arrow.json` kept as text and parsed lazily on the sync path; nested values stringified and kept in `nested_columns`; `arrow.uuid` stringified with NumPy; uint64 values above 2**63−1 stringify the whole column, matching the row constructor's overflow fallback. The row constructor is unchanged. |
| `superset/db_engine_specs/base.py` | `supports_arrow_result = False` (engines opt in one at a time). `fetch_arrow` accepts `to_arrow_reader`, `fetch_record_batch` (ADBC), `to_arrow_table`, or `fetch_arrow_table`, and returns None when the cursor has none of them. `maybe_fetch_arrow` is the production gate: feature flag `ARROW_NATIVE_RESULT_SET` and the engine capability. `get_datatype_from_arrow_field` reads `<VENDOR>:type` metadata. |
| `superset/db_engine_specs/postgres.py` | Opts in. psycopg2 still has no Arrow fetch, so it stays on `fetch_data`. Maps ADBC `POSTGRESQL:type` names through the built-in OIDs and `get_datatype`, so `.columns` type strings match the psycopg2 row path. |
| `superset/db_engine_specs/duckdb.py` | Opts in. DuckDB can return a Table through `to_arrow_reader` / `to_arrow_table` without ADBC. MotherDuck inherits the flag. |
| `superset/db_engine_specs/flightsql.py` | Sketch of a generic Flight SQL spec (`flightsql+adbc://`). An example opt-in, not a requirement of `from_arrow`. |
| `superset/models/core.py` | `Database.get_df` (chart and dataset queries) uses `maybe_fetch_arrow` and then `from_arrow`. When that returns None, `fetch_data` is unchanged. The method still returns a DataFrame via `to_pandas_df()`. |
| `superset/sql_lab.py` | `_read_sqllab_payload`, used by `_execute_query`: Arrow when `maybe_fetch_arrow` returns a table, then `from_arrow`. The row path keeps the limit+1 trim and `limiting_factor`. JSON serialization (`_serialize_and_expand_data`) is unchanged. |
| `superset/sql/execution/executor.py` | `_result_set_for_statement`, used by sync `Database.execute` and the async Celery task. Arrow fetches `row_limit + 1` and sets `truncated` from that extra row. The row fallback still uses `_LimitedCursor` and its truncation probe. |
| `superset/config.py` | `ARROW_NATIVE_RESULT_SET: False`. Global rollback. Default behavior stays the row path. |
| `pyproject.toml` | Optional `flightsql` extra, marker-limited to Python >= 3.12 because sqlalchemy-adbc requires it. Not installed by `just venv`. |
| `tests/unit_tests/result_set_from_arrow_test.py` | Compares `from_arrow` to the row constructor for timestamps, decimals, large integers, nulls, non-finite floats, and the other normalizations above. |

Deliberately out of scope, for a later upstream review:

* Chart-data Arrow on the wire and the frontend shim (draft apache/superset#45363).
* `get_df` is also used by alerts and SQL Lab export, so they share this gate once the flag is on. Metadata probes in `connectors/sqla/utils.py`, and `Database.fetch_rows`, stay on `fetch_data`. SQL Lab's results read-back decodes whatever execute stored; it does not fetch again. The browser payload stays JSON unless the results backend is storing IPC, which it already did.
* Postgres interval normalization. `fetch_data` converts timedeltas to milliseconds before the row constructor. `from_arrow` does not. Pinned as a known gap.
* A non-finite `Decimal` makes the row constructor stringify the whole column, because `pa.array` rejects it. `from_arrow` nulls only those cells and keeps finite values as decimals.
* sqlalchemy-adbc reflection (#45937).

`Database.get_df` still materializes a DataFrame after the result set. This patch does not change that.
