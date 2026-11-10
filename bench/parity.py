"""Type/value parity between the current row path and the Arrow path.

For each backend, the same query is materialized three ways:
  rows       classic driver -> fetch_data -> SupersetResultSet(...)
  adbc_rows  ADBC driver    -> fetch_data -> SupersetResultSet(...)
  arrow      ADBC driver    -> fetch_arrow -> SupersetResultSet.from_arrow(...)

and compared on: pa_table schema, .columns (type / type_generic / is_dttm),
sync-path records (Superset's to_pandas_df + df_to_records), IPC payload
values (pa_table), and nested_columns. No pandas in this module. Used by the pytest
golden tests and by `just parity` to write docs/type-parity.md.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import logging
import os
import sys
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from run_one import spec_for  # noqa: E402

logging.disable(logging.WARNING)


def materialize(backend: str, path: str, sql: str):
    from superset.result_set import SupersetResultSet

    spec = spec_for(backend, path)
    conn = common.connection_for(backend, path)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if path == "arrow":
            rs = SupersetResultSet.from_arrow(spec.fetch_arrow(cur), spec)
        else:
            rs = SupersetResultSet(spec.fetch_data(cur), cur.description, spec)
        cur.close()
    finally:
        conn.close()
    return rs


def canon(value: Any) -> Any:
    """Canonical comparable form of one cell (stdlib + duck typing, no pandas)."""
    if value is None:
        return None
    if type(value).__name__ in ("NaTType", "NAType"):  # Superset/pandas missing
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    if type(value).__name__ == "ndarray":
        return ("ndarray", json.dumps(value.tolist(), sort_keys=True, default=str))
    if hasattr(value, "to_pydatetime"):  # pandas Timestamp from Superset's df
        value = value.to_pydatetime()
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            return ("tz", value.astimezone(dt.timezone.utc).replace(tzinfo=None).isoformat())
        return ("naive", value.isoformat())
    if isinstance(value, dt.date):
        return ("date", value.isoformat())
    if isinstance(value, decimal.Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return ("dec", text)
    if isinstance(value, float):
        return ("f", repr(value))
    if hasattr(value, "item") and not isinstance(value, (bytes, str)):  # numpy scalar
        return canon(value.item())
    if isinstance(value, uuid.UUID):
        return ("str", str(value))
    if isinstance(value, (dict, list)):
        return ("json", json.dumps(value, sort_keys=True))
    if isinstance(value, bytes):
        return ("bytes", value.hex())
    return (type(value).__name__, value)


def describe(rs) -> dict[str, Any]:
    """
    Our code never imports or inspects pandas. Superset's sync SQL Lab path is
    observed through Superset's own functions only: ``to_pandas_df()`` followed
    by ``superset.dataframe.df_to_records(..., convert_decimals=True)``, exactly
    as ``sql_lab._serialize_and_expand_data`` does; we compare the records.
    """
    from superset.dataframe import df_to_records

    records = df_to_records(rs.to_pandas_df(), convert_decimals=True)
    names = rs.pa_table.column_names
    by_col = {c: [row.get(c) for row in records] for c in names}
    return {
        "arrow_types": {f.name: str(f.type) for f in rs.pa_table.schema},
        "columns": {
            c["column_name"]: (c["type"], str(c["type_generic"]), c["is_dttm"])
            for c in rs.columns
        },
        "py_types": {
            c: sorted({type(v).__name__ for v in vals if canon(v) is not None})
            for c, vals in by_col.items()
        },
        # what the sync path (to_pandas_df -> df_to_records) returns
        "values": {c: [canon(v) for v in vals] for c, vals in by_col.items()},
        # what the msgpack/IPC path (RESULTS_BACKEND_USE_MSGPACK) ships
        "ipc_values": {
            f.name: [canon(v) for v in rs.pa_table.column(f.name).to_pylist()]
            for f in rs.pa_table.schema
        },
        "nested_columns": sorted(rs.nested_columns),
    }


def compare(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-column differences between two describe() outputs."""
    out = []
    for col in a["arrow_types"]:
        diff: dict[str, Any] = {"column": col}
        for key in ("arrow_types", "columns", "py_types"):
            if a[key].get(col) != b[key].get(col):
                diff[key] = (a[key].get(col), b[key].get(col))
        va, vb = a["values"][col], b["values"][col]
        if va != vb:
            n = sum(1 for x, y in zip(va, vb) if x != y)
            first = next(i for i, (x, y) in enumerate(zip(va, vb)) if x != y)
            diff["values"] = {"n_diff": n, "example": (va[first], vb[first])}
        ia, ib = a["ipc_values"][col], b["ipc_values"][col]
        if ia != ib:
            n = sum(1 for x, y in zip(ia, ib) if x != y)
            first = next(i for i, (x, y) in enumerate(zip(ia, ib)) if x != y)
            diff["ipc_values"] = {"n_diff": n, "example": (ia[first], ib[first])}
        na, nb = col in a["nested_columns"], col in b["nested_columns"]
        if na != nb:
            diff["nested_columns"] = (na, nb)
        if len(diff) > 1:
            out.append(diff)
    return out


# Edge cases beyond the benchmark table, per backend: (expression, alias).
_PG_EDGE = [
    ("1::int", "dup"),
    ("2::int", "dup"),
    ("'NaN'::numeric", "numeric_nan"),
    ("123456789012345678901234567890.123456789::numeric", "numeric_wide"),
    ("interval '1 day 02:03:04'", "iv"),
    ("ARRAY[1, 2, NULL]::int[]", "int_array"),
    ("'{\"a\": [1, 2]}'::jsonb", "jsonb_obj"),
    ("'5'::json", "json_scalar"),
    ("'\\xdeadbeef'::bytea", "raw_bytes"),
    ("timestamptz '2024-06-01 12:00:00+05:45'", "ts_offset"),
    ("timestamp '9999-12-31 23:59:59'", "ts_far_future"),
    ("NULL::text", "all_null"),
]
_DUCK_EDGE = [
    ("1::INTEGER", "dup"),
    ("2::INTEGER", "dup"),
    ("123456789012345678.1234::DECIMAL(38, 4)", "dec_wide"),
    ("INTERVAL '1 day 02:03:04'", "iv"),
    ("[1, 2, NULL]", "int_list"),
    ("{'a': 1, 'b': 'x'}", "struct_col"),
    ("'b'::ENUM ('a', 'b')", "enum_col"),
    ("'5'::JSON", "json_scalar"),
    ("'\\xDE\\xAD'::BLOB", "raw_bytes"),
    ("TIMESTAMPTZ '2024-06-01 12:00:00+05:45'", "ts_offset"),
    ("TIMESTAMP '9999-12-31 23:59:59'", "ts_far_future"),
    ("NULL::VARCHAR", "all_null"),
]
EDGE_COLUMNS = {
    "postgres": _PG_EDGE,
    "duckdb": _DUCK_EDGE,
    "flightsql": _DUCK_EDGE,
}


def edge_sql(backend: str, only: str | None = None) -> str:
    cols = [(e, a) for e, a in EDGE_COLUMNS[backend] if only is None or a == only]
    return "SELECT " + ", ".join(f"{e} AS {a}" for e, a in cols)


def _bisect_failing_columns(backend: str, path: str) -> str:
    """Re-run the edge query one column at a time to name the culprit(s)."""
    failing = []
    for alias in dict.fromkeys(a for _, a in EDGE_COLUMNS[backend]):
        try:
            materialize(backend, path, edge_sql(backend, alias)).to_pandas_df()
        except Exception as ex:
            failing.append(f"{alias} ({type(ex).__name__}: {str(ex)[:120]})")
    return "failing columns: " + ", ".join(failing)


def run(rows: int = 1000) -> dict[str, Any]:
    app = common.superset_app()
    report: dict[str, Any] = {}
    with app.app_context():
        for backend in common.BACKENDS:
            entry: dict[str, Any] = {}
            for label, sql in (("bench_table", common.select_sql(rows)), ("edge_cases", edge_sql(backend))):
                described = {}
                errors = {}
                for path in common.PATHS:
                    try:
                        described[path] = describe(materialize(backend, path, sql))
                    except Exception as ex:  # record, do not hide
                        errors[path] = f"{type(ex).__name__}: {str(ex)[:300]}"
                        if label == "edge_cases":
                            errors[path] += "; " + _bisect_failing_columns(backend, path)
                section: dict[str, Any] = {"errors": errors}
                for a, b in (("rows", "arrow"), ("adbc_rows", "arrow"), ("rows", "adbc_rows")):
                    if a in described and b in described:
                        section[f"{a}_vs_{b}"] = compare(described[a], described[b])
                section["schemas"] = {
                    p: {"arrow_types": d["arrow_types"], "columns": d["columns"]}
                    for p, d in described.items()
                }
                entry[label] = section
            report[backend] = entry
    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1000)
    ap.add_argument("--out", default=str(common.ROOT / "results" / "type-parity.json"))
    args = ap.parse_args()
    with open(args.out, "w") as fh:
        json.dump(run(args.rows), fh, indent=1, default=str)
    print(f"wrote {args.out}")
