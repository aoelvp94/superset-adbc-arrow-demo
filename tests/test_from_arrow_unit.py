"""Unit tests for the prototype SupersetResultSet.from_arrow (no services)."""

import decimal
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
