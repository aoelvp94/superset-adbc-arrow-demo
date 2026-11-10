"""Golden type-parity tests: current row path vs prototype Arrow path.

Requires `just up` + `just setup-data`. Every divergence found between the
paths must be listed in tests/golden/known_divergences.json (and explained in
docs/type-parity.md); a new divergence, or one that disappears, fails the test.
Regenerate with `just golden-update` after reviewing the diff.
"""

import json
import os

import pytest

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "known_divergences.json")
COMPARISONS = ("rows_vs_arrow", "adbc_rows_vs_arrow")


def signature(report):
    out = {}
    for backend, sections in report.items():
        for section, data in sections.items():
            for cmp in COMPARISONS:
                for diff in data.get(cmp, []):
                    key = f"{backend}/{section}/{cmp}/{diff['column']}"
                    out[key] = sorted(k for k in diff if k != "column")
    return dict(sorted(out.items()))


@pytest.fixture(scope="module")
def report(superset_ctx):
    import parity

    return parity.run(1000)


def test_no_path_errors(report):
    errors = {
        f"{b}/{s}": d["errors"] for b, secs in report.items() for s, d in secs.items() if d["errors"]
    }
    assert errors == {}


def test_divergences_match_golden(report):
    with open(GOLDEN) as fh:
        golden = json.load(fh)
    assert signature(report) == golden


@pytest.mark.parametrize("backend", ["postgres", "duckdb", "flightsql"])
def test_generic_types_and_dttm_match_on_bench_table(report, backend):
    """What drives Explore (type_generic, is_dttm) must not change."""
    for diff in report[backend]["bench_table"]["rows_vs_arrow"]:
        assert "columns" not in diff, diff


@pytest.mark.parametrize("backend", ["postgres", "duckdb"])
def test_dataframe_values_match_on_bench_table(report, backend):
    for diff in report[backend]["bench_table"]["rows_vs_arrow"]:
        assert "values" not in diff, diff
        assert "nested_columns" not in diff, diff


def test_flightsql_values_match_between_adbc_paths(report):
    # flightsql-dbapi (rows) turns DATE into Timestamp; compare against the
    # same ADBC driver to isolate the result-set path.
    for diff in report["flightsql"]["bench_table"]["adbc_rows_vs_arrow"]:
        assert "values" not in diff, diff
