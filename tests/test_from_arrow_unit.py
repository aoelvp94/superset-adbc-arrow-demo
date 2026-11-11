"""Unit tests for SupersetResultSet.from_arrow (no services).

Parity tests compare from_arrow to the existing row constructor. They do not
define a new result contract.
"""

import datetime
import decimal
import math
import uuid

import pyarrow as pa
import pytest


@pytest.fixture()
def rs_cls(superset_ctx):
    from superset.result_set import SupersetResultSet

    return SupersetResultSet


@pytest.fixture()
def spec(superset_ctx):
    from superset.db_engine_specs.base import BaseEngineSpec

    return BaseEngineSpec


def test_duplicate_and_empty_names_match_row_path(rs_cls, spec):
    table = pa.table([pa.array([1]), pa.array([2]), pa.array([3])], names=["a", "a", ""])
    arrow_rs = rs_cls.from_arrow(table, spec)
    row_rs = rs_cls([(1, 2, 3)], [("a",), ("a",), ("",)], spec)
    assert arrow_rs.pa_table.column_names == row_rs.pa_table.column_names == ["a", "a__1", "_col_0"]


def _sync_records(rs):
    """Superset's sync path (to_pandas_df -> df_to_records); no pandas here."""
    from superset.dataframe import df_to_records

    return df_to_records(rs.to_pandas_df(), convert_decimals=True)


def test_dictionary_is_decoded(rs_cls, spec):
    table = pa.table({"c": pa.array(["x", "y", "x"]).dictionary_encode()})
    rs = rs_cls.from_arrow(table, spec)
    assert rs.pa_table.schema.field("c").type == pa.string()
    assert [r["c"] for r in _sync_records(rs)] == ["x", "y", "x"]


def test_opaque_numeric_becomes_decimal_and_nan_is_null(rs_cls, spec):
    opaque = pa.opaque(pa.string(), "numeric", "PostgreSQL")
    storage = pa.array(["1.5", "NaN", None, "-0.0001", "Infinity"])
    table = pa.table({"n": pa.ExtensionArray.from_storage(opaque, storage)})
    rs = rs_cls.from_arrow(table, spec)
    assert rs.pa_table.schema.field("n").type == pa.decimal128(38, 4)
    assert rs.pa_table.column("n").to_pylist() == [
        decimal.Decimal("1.5000"), None, None, decimal.Decimal("-0.0001"), None,
    ]


def test_opaque_numeric_wider_than_38_digits_uses_decimal256(rs_cls, spec):
    opaque = pa.opaque(pa.string(), "numeric", "PostgreSQL")
    value = "123456789012345678901234567890.123456789"
    table = pa.table({"n": pa.ExtensionArray.from_storage(opaque, pa.array([value]))})
    rs = rs_cls.from_arrow(table, spec)
    assert pa.types.is_decimal256(rs.pa_table.schema.field("n").type)
    assert rs.pa_table.column("n")[0].as_py() == decimal.Decimal(value)


def test_json_extension_is_lazy_and_restored_on_sync_path(rs_cls, spec):
    storage = pa.array(['{"a": 1}', None, '[1, 2]'])
    table = pa.table({"j": pa.ExtensionArray.from_storage(pa.json_(), storage)})
    rs = rs_cls.from_arrow(table, spec)
    # IPC path: JSON text untouched, nothing parsed yet
    assert rs.pa_table.column("j").to_pylist() == ['{"a": 1}', None, "[1, 2]"]
    assert rs._lazy_json_columns
    assert [r["j"] for r in _sync_records(rs)] == [{"a": 1}, None, [1, 2]]
    assert rs.nested_columns["j"] == [{"a": 1}, None, [1, 2]]


def test_json_scalars_are_not_nested(rs_cls, spec):
    table = pa.table({"j": pa.ExtensionArray.from_storage(pa.json_(), pa.array(["5", "6"]))})
    rs = rs_cls.from_arrow(table, spec)
    assert "j" not in rs.nested_columns


def test_uuid_extension_is_stringified(rs_cls, spec):
    u = uuid.UUID("c4ca4238-a0b9-2382-0dcc-509a6f75849b")
    table = pa.table({"u": pa.array([u, None], type=pa.uuid())})
    rs = rs_cls.from_arrow(table, spec)
    assert rs.pa_table.column("u").to_pylist() == [str(u), None]


def test_nested_list_and_struct_like_row_path(rs_cls, spec):
    table = pa.table({"l": pa.array([[1, 2], None]), "s": pa.array([{"a": 1}, None])})
    arrow_rs = rs_cls.from_arrow(table, spec)
    row_rs = rs_cls([([1, 2], {"a": 1}), (None, None)], [("l",), ("s",)], spec)
    assert arrow_rs.pa_table.column("l").to_pylist() == row_rs.pa_table.column("l").to_pylist()
    assert arrow_rs.pa_table.column("s").to_pylist() == row_rs.pa_table.column("s").to_pylist()
    assert arrow_rs.nested_columns == row_rs.nested_columns


def test_empty_table(rs_cls, spec):
    table = pa.table({"a": pa.array([], type=pa.int64())})
    rs = rs_cls.from_arrow(table, spec)
    assert rs.size == 0
    assert [c["column_name"] for c in rs.columns] == ["a"]


class _FakeReader:
    def __init__(self, batches):
        self.schema = batches[0].schema
        self._batches = batches

    def __iter__(self):
        return iter(self._batches)

    def read_all(self):
        return pa.Table.from_batches(self._batches)


class _FakeAdbcCursor:
    description = [("a", pa.int64(), None, None, None, None, None)]

    def __init__(self, n_batches=5, batch_rows=10):
        self.read = 0
        self._batches = [
            pa.record_batch({"a": pa.array(range(i * batch_rows, (i + 1) * batch_rows))})
            for i in range(n_batches)
        ]

    def fetch_record_batch(self):
        return _FakeReader(self._batches)


def test_fetch_arrow_respects_limit_and_opt_in(superset_ctx):
    from superset.db_engine_specs.base import BaseEngineSpec
    from superset.db_engine_specs.duckdb import DuckDBEngineSpec

    assert BaseEngineSpec.fetch_arrow(_FakeAdbcCursor()) is None  # not opted in
    table = DuckDBEngineSpec.fetch_arrow(_FakeAdbcCursor(), limit=25)
    assert table.num_rows == 25
    assert DuckDBEngineSpec.fetch_arrow(_FakeAdbcCursor()).num_rows == 50


def test_fetch_arrow_none_for_row_cursor(superset_ctx):
    from superset.db_engine_specs.postgres import PostgresEngineSpec

    class RowCursor:
        description = [("a", 23)]

    assert PostgresEngineSpec.fetch_arrow(RowCursor()) is None


def _same(left, right):
    assert len(left) == len(right)
    for got, expected in zip(left, right, strict=True):
        if isinstance(got, float) and isinstance(expected, float):
            if math.isnan(got) and math.isnan(expected):
                continue
        assert got == expected, (got, expected)


def _assert_matches_row(rs_cls, spec, type_code, values, arrow_column=None, compare_generic=True):
    column = values if arrow_column is None else arrow_column
    row_rs = rs_cls([(value,) for value in values], [("c", type_code)], spec)
    arrow_rs = rs_cls.from_arrow(pa.table({"c": column}), spec)
    _same(arrow_rs.pa_table.column("c").to_pylist(), row_rs.pa_table.column("c").to_pylist())
    # Decimals are not named by convert_pa_dtype. Without driver metadata,
    # do not invent a generic type the row path does not report.
    if compare_generic:
        assert arrow_rs.columns[0]["type_generic"] == row_rs.columns[0]["type_generic"]
        assert bool(arrow_rs.columns[0]["is_dttm"]) == bool(row_rs.columns[0]["is_dttm"])


def test_plain_table_does_not_require_adbc(rs_cls, spec):
    table = pa.table({"a": pa.array([1, None, 0])})
    result = rs_cls.from_arrow(table, spec)
    assert result.pa_table.column("a").to_pylist() == [1, None, 0]
    assert spec.supports_arrow_result is False


def test_timestamps_match_row_path(rs_cls, spec):
    offset = datetime.timezone(datetime.timedelta(hours=5, minutes=45))
    _assert_matches_row(rs_cls, spec, "timestamp", [datetime.datetime(2024, 1, 2, 3, 4, 5), None])
    _assert_matches_row(
        rs_cls, spec, "timestamptz", [datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc), None]
    )
    _assert_matches_row(
        rs_cls,
        spec,
        "timestamptz",
        [datetime.datetime(2024, 6, 1, 12, 30, tzinfo=offset), None],
    )
    _assert_matches_row(rs_cls, spec, "timestamp", [datetime.datetime(9999, 12, 31, 23, 59, 59)])
    _assert_matches_row(
        rs_cls, spec, "timestamptz", [datetime.datetime(3118, 1, 1, tzinfo=datetime.timezone.utc)]
    )


def test_dates_bools_blobs_nulls_and_small_ints_match_row_path(rs_cls, spec):
    _assert_matches_row(rs_cls, spec, "date", [datetime.date(2020, 1, 2), None])
    _assert_matches_row(rs_cls, spec, "bool", [True, False, None])
    _assert_matches_row(rs_cls, spec, "bytea", [b"abc", None, b""])
    _assert_matches_row(rs_cls, spec, "int", [1, None, 0, -3])
    _assert_matches_row(rs_cls, spec, "int", [None, None], pa.array([None, None], type=pa.int64()))


def test_finite_decimals_match_row_path(rs_cls, spec):
    _assert_matches_row(
        rs_cls, spec, "numeric",
        [decimal.Decimal("1.50"), decimal.Decimal("-0.0001"), None],
        compare_generic=False,
    )
    wide = decimal.Decimal("123456789012345678901234567890.123456789")
    _assert_matches_row(rs_cls, spec, "numeric", [wide, None], compare_generic=False)


def test_non_finite_floats_match_row_path(rs_cls, spec):
    _assert_matches_row(
        rs_cls,
        spec,
        "float8",
        [float("nan"), float("inf"), float("-inf"), 1.5, 0.0, None],
    )


def test_uint64_above_int64_matches_row_stringification(rs_cls, spec):
    big = 2**64 - 1
    values = [1, big, 0, None]
    _assert_matches_row(rs_cls, spec, "int", values, pa.array(values, type=pa.uint64()))


def test_uint64_that_fits_keeps_equal_values(rs_cls, spec):
    values = [1, 2, None]
    arrow_rs = rs_cls.from_arrow(pa.table({"c": pa.array(values, type=pa.uint64())}), spec)
    row_rs = rs_cls([(value,) for value in values], [("c", "int")], spec)
    _same(arrow_rs.pa_table.column("c").to_pylist(), row_rs.pa_table.column("c").to_pylist())
    assert pa.types.is_uint64(arrow_rs.pa_table.schema.field("c").type)


def test_int64_safe_and_beyond_js_safe_stay_integers(rs_cls, spec):
    """The row path stringifies only when the value does not fit in int64."""
    value = 2**53 + 1
    _assert_matches_row(rs_cls, spec, "int", [value, -value, None])
    result = rs_cls.from_arrow(pa.table({"c": [value, -value, None]}), spec)
    assert pa.types.is_integer(result.pa_table.schema.field("c").type)


def test_non_finite_decimal_nulls_cells_and_keeps_finite_decimals(rs_cls, spec):
    """
    The row constructor stringifies a whole column when pa.array rejects a
    non-finite Decimal. from_arrow nulls only those cells.
    """
    rows = [
        (decimal.Decimal("1.50"),),
        (decimal.Decimal("NaN"),),
        (decimal.Decimal("Infinity"),),
        (decimal.Decimal("-Infinity"),),
        (None,),
    ]
    row_rs = rs_cls(rows, [("n", "numeric")], spec)
    row_vals = row_rs.pa_table.column("n").to_pylist()
    assert row_vals[1] is None and row_vals[2] is None and row_vals[3] is None
    assert all(value is None or isinstance(value, str) for value in row_vals)

    opaque = pa.opaque(pa.string(), "numeric", "PostgreSQL")
    storage = pa.array(["1.50", "NaN", "Infinity", "-Infinity", None])
    arrow_rs = rs_cls.from_arrow(
        pa.table({"n": pa.ExtensionArray.from_storage(opaque, storage)}), spec
    )
    assert arrow_rs.pa_table.column("n").to_pylist() == [
        decimal.Decimal("1.5000"),
        None,
        None,
        None,
        None,
    ]


def test_duration_is_not_the_postgres_interval_mutator(rs_cls, spec):
    """BaseEngineSpec does not apply the Postgres mutator."""
    table = pa.table({"iv": pa.array([1_000_000], type=pa.duration("us"))})
    arrow_rs = rs_cls.from_arrow(table, spec)
    row_rs = rs_cls([(1000.0,)], [("iv", "interval")], spec)
    assert pa.types.is_duration(arrow_rs.pa_table.schema.field("iv").type)
    assert row_rs.pa_table.column("iv").to_pylist() == [1000.0]
    assert arrow_rs.pa_table.column("iv").to_pylist() != row_rs.pa_table.column("iv").to_pylist()


def test_postgres_interval_matches_fetch_data_milliseconds(rs_cls, superset_ctx):
    """
    1 day 02:03:04 is 93784000.0 ms. A year is 365 days and a month is 30,
    matching the timedelta psycopg2 hands to fetch_data. DuckDB is unchanged.
    """
    from datetime import timedelta

    from superset.db_engine_specs.duckdb import DuckDBEngineSpec
    from superset.db_engine_specs.postgres import PostgresEngineSpec, _normalize_interval

    nanos = (2 * 3600 + 3 * 60 + 4) * 1_000_000_000
    values = [(0, 1, nanos), (14, 3, 0), (-14, 0, -1_000_000_000), None]
    array = pa.array(values, type=pa.month_day_nano_interval())
    field = pa.field(
        "iv",
        pa.month_day_nano_interval(),
        metadata={b"POSTGRESQL:type": b"interval"},
    )
    table = pa.Table.from_arrays([array], schema=pa.schema([field]))
    arrow_rs = rs_cls.from_arrow(table, PostgresEngineSpec)
    expected = [
        93784000.0,
        _normalize_interval(timedelta(days=365 + 30 * 2 + 3)),
        _normalize_interval(timedelta(days=-(365 + 30 * 2), microseconds=-1_000_000)),
        None,
    ]
    assert arrow_rs.pa_table.column("iv").to_pylist() == expected
    assert arrow_rs.columns[0]["type"] == PostgresEngineSpec.get_datatype(1186)
    row_rs = rs_cls(
        [(value,) for value in expected],
        [("iv", arrow_rs.columns[0]["type"])],
        PostgresEngineSpec,
    )
    assert arrow_rs.pa_table.column("iv").to_pylist() == row_rs.pa_table.column("iv").to_pylist()

    duration = pa.table({"iv": pa.array([1_000_000, None], type=pa.duration("us"))})
    assert rs_cls.from_arrow(duration, PostgresEngineSpec).pa_table.column("iv").to_pylist() == [
        1000.0,
        None,
    ]

    duck = rs_cls.from_arrow(
        pa.table({"iv": pa.array([(0, 1, 0)], type=pa.month_day_nano_interval())}),
        DuckDBEngineSpec,
    )
    assert pa.types.is_interval(duck.pa_table.schema.field("iv").type)


def test_fetch_arrow_accepts_a_table_without_adbc(superset_ctx):
    """A cursor that only has to_arrow_table (no fetch_record_batch) still works."""
    from superset.db_engine_specs.duckdb import DuckDBEngineSpec

    class TableCursor:
        description = [("a", pa.int64())]

        def to_arrow_table(self):
            return pa.table({"a": pa.array([1, 2, 3, 4, 5])})

    table = DuckDBEngineSpec.fetch_arrow(TableCursor(), limit=2)
    assert table.column("a").to_pylist() == [1, 2]


def test_engines_opt_in_individually_and_the_flag_defaults_off(superset_ctx):
    from superset import feature_flag_manager
    from superset.db_engine_specs.base import BaseEngineSpec
    from superset.db_engine_specs.duckdb import DuckDBEngineSpec
    from superset.db_engine_specs.flightsql import FlightSQLEngineSpec
    from superset.db_engine_specs.mysql import MySQLEngineSpec
    from superset.db_engine_specs.postgres import PostgresEngineSpec

    assert BaseEngineSpec.supports_arrow_result is False
    assert MySQLEngineSpec.supports_arrow_result is False
    assert DuckDBEngineSpec.supports_arrow_result is True
    assert PostgresEngineSpec.supports_arrow_result is True
    assert FlightSQLEngineSpec.supports_arrow_result is True
    assert feature_flag_manager.is_feature_enabled("ARROW_NATIVE_RESULT_SET") is False

    class Cursor:
        def __init__(self):
            self.description = [("a", "int")]
            self.consumed = False

        def fetch_record_batch(self):
            self.consumed = True
            return pa.table({"a": [1]})

    cursor = Cursor()
    assert DuckDBEngineSpec.maybe_fetch_arrow(cursor) is None
    assert cursor.consumed is False

    flags = feature_flag_manager._feature_flags
    previous = flags.get("ARROW_NATIVE_RESULT_SET")
    flags["ARROW_NATIVE_RESULT_SET"] = True
    try:
        table = DuckDBEngineSpec.maybe_fetch_arrow(cursor)
        assert table.num_rows == 1
        assert cursor.consumed is True
        assert BaseEngineSpec.maybe_fetch_arrow(Cursor()) is None
    finally:
        if previous is None:
            flags.pop("ARROW_NATIVE_RESULT_SET", None)
        else:
            flags["ARROW_NATIVE_RESULT_SET"] = previous


class _LimitQuery:
    def __init__(self, limit):
        self.limit = limit
        self.limiting_factor = "QUERY"


class _BothCursor:
    """Arrow table plus a consuming row fetch, so either path can run."""

    def __init__(self, values):
        self.description = [("a", "int")]
        self.values = list(values)
        self.arrow_reads = 0
        self._rows = [(value,) for value in values]

    def to_arrow_table(self):
        self.arrow_reads += 1
        return pa.table({"a": pa.array(self.values, type=pa.int64())})

    def fetchmany(self, size=None):
        if size is None:
            size = len(self._rows)
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def fetchall(self):
        return self.fetchmany(len(self._rows))


class _RowOnlyCursor:
    """Row fetch only. Opted-in engines still fall back when this is the cursor."""

    def __init__(self, values):
        self.description = [("a", "int")]
        self._rows = [(value,) for value in values]

    def fetchmany(self, size=None):
        if size is None:
            size = len(self._rows)
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def fetchall(self):
        return self.fetchmany(len(self._rows))


def _with_flag(on):
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        from superset import feature_flag_manager

        flags = feature_flag_manager._feature_flags
        previous = flags.get("ARROW_NATIVE_RESULT_SET")
        flags["ARROW_NATIVE_RESULT_SET"] = on
        try:
            yield
        finally:
            if previous is None:
                flags.pop("ARROW_NATIVE_RESULT_SET", None)
            else:
                flags["ARROW_NATIVE_RESULT_SET"] = previous

    return _ctx()


def _json_records(result):
    from superset.dataframe import df_to_records

    return df_to_records(result.to_pandas_df(), convert_decimals=True) or []


def test_sqllab_stays_on_rows_when_the_flag_is_off(superset_ctx):
    from superset.db_engine_specs.duckdb import DuckDBEngineSpec
    from superset.sql_lab import _read_sqllab_payload

    cursor = _BothCursor([1, 2, 3])
    query = _LimitQuery(2)
    with _with_flag(False):
        table, rows = _read_sqllab_payload(query, cursor, DuckDBEngineSpec)
    assert table is None
    assert cursor.arrow_reads == 0
    assert rows == [(1,), (2,)]
    assert query.limiting_factor == "QUERY"
    from superset.result_set import SupersetResultSet

    assert _json_records(SupersetResultSet(rows, cursor.description, DuckDBEngineSpec)) == [
        {"a": 1},
        {"a": 2},
    ]


def test_sqllab_uses_arrow_and_drops_the_extra_limit_row(superset_ctx):
    from superset.db_engine_specs.duckdb import DuckDBEngineSpec
    from superset.result_set import SupersetResultSet
    from superset.sql_lab import _read_sqllab_payload
    from superset.sqllab.limiting_factor import LimitingFactor

    cursor = _BothCursor([1, 2, 3])
    query = _LimitQuery(2)
    with _with_flag(True):
        table, rows = _read_sqllab_payload(query, cursor, DuckDBEngineSpec)
    assert rows is None
    assert cursor.arrow_reads == 1
    assert query.limiting_factor == "QUERY"
    result = SupersetResultSet.from_arrow(table, DuckDBEngineSpec)
    assert result.pa_table.column("a").to_pylist() == [1, 2]
    assert _json_records(result) == [{"a": 1}, {"a": 2}]

    fitting = _LimitQuery(10)
    with _with_flag(True):
        table, rows = _read_sqllab_payload(fitting, _BothCursor([1, 2]), DuckDBEngineSpec)
    assert rows is None
    assert fitting.limiting_factor == LimitingFactor.NOT_LIMITED
    assert table.num_rows == 2


def test_sqllab_falls_back_without_arrow_or_without_opt_in(superset_ctx):
    from superset.db_engine_specs.base import BaseEngineSpec
    from superset.db_engine_specs.duckdb import DuckDBEngineSpec
    from superset.sql_lab import _read_sqllab_payload
    from superset.sqllab.limiting_factor import LimitingFactor

    # Opted-in engine, cursor with no Arrow method (psycopg2's situation).
    row_cursor = _RowOnlyCursor([1, 2, 3])
    query = _LimitQuery(2)
    with _with_flag(True):
        table, rows = _read_sqllab_payload(query, row_cursor, DuckDBEngineSpec)
    assert table is None
    assert rows == [(1,), (2,)]

    # Cursor can produce a Table, but this engine has not opted in.
    arrow_cursor = _BothCursor([7])
    open_query = _LimitQuery(None)
    with _with_flag(True):
        table, rows = _read_sqllab_payload(open_query, arrow_cursor, BaseEngineSpec)
    assert table is None
    assert arrow_cursor.arrow_reads == 0
    assert rows == [(7,)]
    assert open_query.limiting_factor == LimitingFactor.NOT_LIMITED


def test_executor_arrow_opt_in_and_row_fallback(superset_ctx):
    from superset.db_engine_specs.duckdb import DuckDBEngineSpec
    from superset.sql.execution.executor import _result_set_for_statement

    with _with_flag(True):
        truncated = _result_set_for_statement(
            DuckDBEngineSpec, _BothCursor([1, 2, 3]), row_limit=2
        )
        exact = _result_set_for_statement(
            DuckDBEngineSpec, _BothCursor([1, 2]), row_limit=2
        )
        unlimited = _result_set_for_statement(
            DuckDBEngineSpec, _BothCursor([1, 2, 3]), row_limit=None
        )
    assert truncated.truncated is True
    assert truncated.pa_table.column("a").to_pylist() == [1, 2]
    assert _json_records(truncated) == [{"a": 1}, {"a": 2}]
    assert exact.truncated is False and exact.size == 2
    assert unlimited.truncated is False and unlimited.size == 3

    cursor = _BothCursor([1, 2, 3])
    with _with_flag(False):
        fallback = _result_set_for_statement(DuckDBEngineSpec, cursor, row_limit=2)
        short = _result_set_for_statement(DuckDBEngineSpec, _BothCursor([1]), row_limit=2)
    assert cursor.arrow_reads == 0
    assert fallback.truncated is True
    assert fallback.pa_table.column("a").to_pylist() == [1, 2]
    assert short.truncated is False
    assert short.pa_table.column("a").to_pylist() == [1]
