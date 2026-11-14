"""Parity matrix: from_arrow vs the row constructor, down to the DataFrame.

The chart cache stores the DataFrame and its key does not say which ingest
path built it, so values and dtypes of to_pandas_df() must match too. Known,
intentional differences are pinned explicitly instead of being skipped.
"""

import datetime
import decimal
import math
import zoneinfo

import pandas as pd
import pyarrow as pa
import pytest


@pytest.fixture()
def rs_cls(superset_ctx):
    from superset.result_set import SupersetResultSet

    return SupersetResultSet


@pytest.fixture()
def base(superset_ctx):
    from superset.db_engine_specs.base import BaseEngineSpec

    return BaseEngineSpec


@pytest.fixture()
def postgres(superset_ctx):
    from superset.db_engine_specs.postgres import PostgresEngineSpec

    return PostgresEngineSpec


def _cell_equal(left, right):
    if left is None or right is None:
        return left is right
    if isinstance(left, float) and isinstance(right, float):
        return (math.isnan(left) and math.isnan(right)) or left == right
    if left is pd.NaT or right is pd.NaT:
        return left is right
    try:
        if pd.isna(left) and pd.isna(right):
            return True
    except (TypeError, ValueError):
        pass
    return left == right


def _pair(rs_cls, spec, type_code, values, arrow_column=None, field=None):
    column = values if arrow_column is None else arrow_column
    row_rs = rs_cls([(value,) for value in values], [("c", type_code)], spec)
    if field is None:
        table = pa.table({"c": column})
    else:
        table = pa.Table.from_arrays([pa.array(column, type=field.type)], schema=pa.schema([field]))
    return row_rs, rs_cls.from_arrow(table, spec)


def _assert_df_parity(row_rs, arrow_rs, *, dtype=True):
    row_df, arrow_df = row_rs.to_pandas_df(), arrow_rs.to_pandas_df()
    assert list(arrow_df.columns) == list(row_df.columns)
    if dtype:
        assert arrow_df.dtypes.to_dict() == row_df.dtypes.to_dict()
    for name in row_df.columns:
        got, expected = arrow_df[name].tolist(), row_df[name].tolist()
        assert len(got) == len(expected)
        for a, b in zip(got, expected, strict=True):
            assert _cell_equal(a, b), (name, a, b)


def _assert_records_parity(row_rs, arrow_rs):
    from superset.dataframe import df_to_records

    assert df_to_records(arrow_rs.to_pandas_df()) == df_to_records(row_rs.to_pandas_df())


def _assert_columns_parity(row_rs, arrow_rs, keys=("type_generic", "is_dttm")):
    for key in keys:
        assert arrow_rs.columns[0][key] == row_rs.columns[0][key], key


# Timestamps with time zones

@pytest.mark.parametrize(
    "tz",
    [
        datetime.UTC,
        datetime.timezone(datetime.timedelta(hours=5, minutes=45)),
        datetime.timezone(datetime.timedelta(hours=-3, minutes=-30)),
        zoneinfo.ZoneInfo("America/New_York"),
    ],
    ids=["utc", "plus0545", "minus0330", "new_york"],
)
def test_tz_aware_timestamps_dataframe_parity(rs_cls, base, tz):
    values = [
        datetime.datetime(2024, 3, 10, 6, 59, tzinfo=tz),
        datetime.datetime(2024, 3, 10, 7, 1, tzinfo=tz),
        None,
        datetime.datetime(2024, 11, 3, 5, 30, tzinfo=tz),
    ]
    row_rs, arrow_rs = _pair(rs_cls, base, "timestamptz", values)
    _assert_columns_parity(row_rs, arrow_rs)
    _assert_df_parity(row_rs, arrow_rs)


def test_naive_timestamps_and_far_future_dataframe_parity(rs_cls, base):
    values = [datetime.datetime(2024, 1, 2, 3, 4, 5, 123456), None]
    row_rs, arrow_rs = _pair(rs_cls, base, "timestamp", values)
    _assert_columns_parity(row_rs, arrow_rs)
    _assert_df_parity(row_rs, arrow_rs)
    far = [datetime.datetime(9999, 12, 31, 23, 59, 59), None]
    row_rs, arrow_rs = _pair(rs_cls, base, "timestamp", far)
    _assert_df_parity(row_rs, arrow_rs)


def test_all_null_timestamptz_column_is_a_pinned_dtype_difference(rs_cls, base):
    """The row path builds an Arrow null column; Arrow keeps the declared type."""
    row_rs, arrow_rs = _pair(
        rs_cls, base, "timestamptz", [None, None],
        pa.array([None, None], type=pa.timestamp("us", tz="UTC")),
    )
    _assert_records_parity(row_rs, arrow_rs)
    _assert_columns_parity(row_rs, arrow_rs, keys=("type_generic",))
    assert row_rs.to_pandas_df()["c"].dtype == object
    assert str(arrow_rs.to_pandas_df()["c"].dtype) == "datetime64[us, UTC]"


# Finite decimals

@pytest.mark.parametrize(
    "values",
    [
        [decimal.Decimal("1.50"), decimal.Decimal("-0.0001"), None],
        [decimal.Decimal(0), decimal.Decimal("-0"), decimal.Decimal("99999999999999.9999")],
        [decimal.Decimal("123456789012345678901234567890.123456789"), None],
    ],
    ids=["small", "zero_and_max18_4", "wider_than_38"],
)
def test_finite_decimals_dataframe_values(rs_cls, base, values):
    row_rs, arrow_rs = _pair(rs_cls, base, "numeric", values)
    _assert_df_parity(row_rs, arrow_rs)


# Integers around the int64 and uint64 limits

def test_int64_boundaries(rs_cls, base):
    values = [2**63 - 1, -(2**63), 0, None]
    row_rs, arrow_rs = _pair(rs_cls, base, "int8", values)
    _assert_columns_parity(row_rs, arrow_rs)
    _assert_df_parity(row_rs, arrow_rs)


@pytest.mark.parametrize("big", [2**63, 2**64 - 1], ids=["2_63", "uint64_max"])
def test_uint64_above_int64_dataframe_parity(rs_cls, base, big):
    values = [1, big, None]
    row_rs, arrow_rs = _pair(rs_cls, base, "int", values, pa.array(values, type=pa.uint64()))
    _assert_df_parity(row_rs, arrow_rs)
    assert arrow_rs.columns[0]["type"] == row_rs.columns[0]["type"]


def test_int32_width_is_a_pinned_dtype_difference(rs_cls, base):
    """Arrow keeps the server's int32; the row path re-infers int64. Values equal."""
    values = [1, -3, None]
    row_rs, arrow_rs = _pair(rs_cls, base, "int4", values, pa.array(values, type=pa.int32()))
    _assert_df_parity(row_rs, arrow_rs, dtype=False)
    assert pa.types.is_int64(row_rs.pa_table.schema.field("c").type)
    assert pa.types.is_int32(arrow_rs.pa_table.schema.field("c").type)


# Nulls

@pytest.mark.parametrize(
    "arrow_type,type_code",
    [
        (pa.int64(), "int8"),
        (pa.float64(), "float8"),
        (pa.string(), "text"),
        (pa.bool_(), "bool"),
        (pa.date32(), "date"),
    ],
    ids=["int", "float", "text", "bool", "date"],
)
def test_all_null_columns_serialize_the_same(rs_cls, base, arrow_type, type_code):
    """
    Records match. The DataFrame dtype can differ: the row path's Arrow null
    column becomes object/None, while a typed float or string column becomes
    NaN, which df_to_records turns back into None.
    """
    row_rs, arrow_rs = _pair(rs_cls, base, type_code, [None, None], pa.array([None, None], type=arrow_type))
    _assert_records_parity(row_rs, arrow_rs)
    assert pa.types.is_null(row_rs.pa_table.schema.field("c").type)
    assert arrow_rs.pa_table.schema.field("c").type == arrow_type


def test_nullable_integers_stay_objects_with_none(rs_cls, base):
    row_rs, arrow_rs = _pair(rs_cls, base, "int8", [1, None, 3])
    _assert_df_parity(row_rs, arrow_rs)
    assert arrow_rs.to_pandas_df()["c"].tolist()[1] is None


# Non-finite floats

@pytest.mark.parametrize("arrow_type", [pa.float64(), pa.float32()], ids=["float64", "float32"])
def test_non_finite_floats_dataframe_parity(rs_cls, base, arrow_type):
    values = [float("nan"), float("inf"), float("-inf"), 1.5, None]
    row_rs, arrow_rs = _pair(rs_cls, base, "float8", values, pa.array(values, type=arrow_type))
    _assert_df_parity(row_rs, arrow_rs, dtype=arrow_type == pa.float64())


# Dates

def test_dates_dataframe_parity(rs_cls, base):
    values = [datetime.date(2020, 2, 29), datetime.date(1, 1, 1), datetime.date(9999, 12, 31), None]
    row_rs, arrow_rs = _pair(rs_cls, base, "date", values)
    _assert_columns_parity(row_rs, arrow_rs)
    _assert_df_parity(row_rs, arrow_rs)


def test_date64_values_match_date32(rs_cls, base):
    values = [datetime.date(2020, 1, 2), None]
    row_rs, arrow_rs = _pair(rs_cls, base, "date", values, pa.array(values, type=pa.date64()))
    _assert_df_parity(row_rs, arrow_rs, dtype=False)


# Nested values

@pytest.mark.parametrize(
    "values",
    [
        [[1, 2, None], [], None],
        [{"a": 1, "b": "x"}, {"a": None, "b": None}, None],
        [[{"k": [1, 2]}], [], None],
    ],
    ids=["list_with_nulls_and_empty", "struct_with_nulls", "list_of_struct_of_list"],
)
def test_nested_values_dataframe_and_sidecar_parity(rs_cls, base, values):
    row_rs, arrow_rs = _pair(rs_cls, base, "json", values)
    assert arrow_rs.nested_columns == row_rs.nested_columns
    assert arrow_rs.pa_table.column("c").to_pylist() == row_rs.pa_table.column("c").to_pylist()
    _assert_df_parity(row_rs, arrow_rs)


# Vendor metadata

def test_postgres_vendor_metadata_wins_over_arrow_inference(rs_cls, postgres):
    field = pa.field("c", pa.int64(), metadata={b"POSTGRESQL:type": b"int8"})
    row_rs, arrow_rs = _pair(rs_cls, postgres, 20, [1, None], field=field)
    assert arrow_rs.columns[0]["type"] == row_rs.columns[0]["type"] == postgres.get_datatype(20)
    assert arrow_rs.columns[0]["type"] != rs_cls.convert_pa_dtype(pa.int64())


@pytest.mark.parametrize(
    "typname,oid,arrow_type",
    [
        (b"timestamptz", 1184, pa.timestamp("us", tz="UTC")),
        (b"date", 1082, pa.date32()),
        (b"numeric", 1700, pa.decimal128(10, 2)),
        (b"text", 25, pa.string()),
        (b"bool", 16, pa.bool_()),
    ],
)
def test_postgres_vendor_metadata_matches_psycopg2_type_strings(rs_cls, postgres, typname, oid, arrow_type):
    field = pa.field("c", arrow_type, metadata={b"POSTGRESQL:type": typname})
    arrow_rs = rs_cls.from_arrow(pa.Table.from_arrays([pa.array([None], type=arrow_type)], schema=pa.schema([field])), postgres)
    assert arrow_rs.columns[0]["type"] == postgres.get_datatype(oid)


def test_without_metadata_falls_back_to_convert_pa_dtype(rs_cls, postgres):
    arrow_rs = rs_cls.from_arrow(pa.table({"c": pa.array([1.5], type=pa.float64())}), postgres)
    assert arrow_rs.columns[0]["type"] == rs_cls.convert_pa_dtype(pa.float64())


def test_unknown_postgres_typname_does_not_invent_a_type(rs_cls, postgres):
    field = pa.field("c", pa.string(), metadata={b"POSTGRESQL:type": b"tsvector"})
    arrow_rs = rs_cls.from_arrow(pa.Table.from_arrays([pa.array(["a"])], schema=pa.schema([field])), postgres)
    assert arrow_rs.columns[0]["type"] == rs_cls.convert_pa_dtype(pa.string())
