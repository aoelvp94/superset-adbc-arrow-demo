# superset-adbc-arrow-bench: local-only, reproducible.
# Requires: docker (compose v2), uv, just, git. Python 3.11 is fetched by uv.

set shell := ["bash", "-euo", "pipefail", "-c"]
set export

SUPERSET_COMMIT := `cat SUPERSET_COMMIT`
SUPERSET_SRC := justfile_directory() / ".cache/superset"
VENV := justfile_directory() / ".venv"
PY := VENV / "bin/python"
SUPERSET_CONFIG_PATH := justfile_directory() / "bench/superset_config_bench.py"
ROWS := "100000 1000000"
ROUNDS := "5 3"
LARGE_ROWS := "1000000 10000000"
BENCH_MAX_RSS_GB := "5"

default:
    @just --list

# Everything a reviewer needs: services, venv, data, tests, bench, report.
reproduce: up venv setup-data check-datafusion-extra test parity bench bench-large render
    @echo "done: see BENCH.md, results/, docs/type-parity.md"

up:
    docker compose up -d --build --wait

down:
    docker compose down -v

# apache/superset master at SUPERSET_COMMIT + patches/0001 (the prototype).
superset-src:
    if [ ! -d "$SUPERSET_SRC/.git" ]; then \
      git init -q "$SUPERSET_SRC" && \
      git -C "$SUPERSET_SRC" remote add origin https://github.com/apache/superset.git; \
    fi
    git -C "$SUPERSET_SRC" fetch -q --depth 1 origin "$SUPERSET_COMMIT"
    git -C "$SUPERSET_SRC" checkout -q -f FETCH_HEAD
    git -C "$SUPERSET_SRC" clean -qfd
    git -C "$SUPERSET_SRC" apply --index {{justfile_directory()}}/patches/0001-arrow-native-result-set.patch
    @echo "superset $SUPERSET_COMMIT + patch applied in $SUPERSET_SRC"

venv: superset-src
    uv venv -q -p 3.11 "$VENV" --allow-existing
    VIRTUAL_ENV="$VENV" uv pip install -q -r requirements.txt "$SUPERSET_SRC[postgres,duckdb]"
    # flightsql-dbapi (Superset's DataFusion driver) pins sqlalchemy<2, which
    # Superset master rejects; install it without deps to bench its fetch path.
    VIRTUAL_ENV="$VENV" uv pip install -q --no-deps "flightsql-dbapi==0.2.2"
    VIRTUAL_ENV="$VENV" uv pip freeze > results/pip-freeze.txt

setup-data:
    {{PY}} bench/setup_data.py --rows 1000 {{ROWS}} {{LARGE_ROWS}}

# Task A: is apache-superset[datafusion] resolvable? (writes evidence/task-a)
check-datafusion-extra:
    bash scripts/check_datafusion_extra.sh

test:
    {{PY}} -m pytest -q tests

# Upstream-style unit tests shipped inside the patch, run in the patched tree.
test-upstream:
    cd "$SUPERSET_SRC" && SUPERSET_TESTENV=true {{PY}} -m pytest -q -p no:cacheprovider \
      tests/unit_tests/result_set_from_arrow_test.py tests/unit_tests/result_set_test.py \
      tests/unit_tests/db_engine_specs/test_postgres.py tests/unit_tests/db_engine_specs/test_duckdb.py \
      tests/unit_tests/db_engine_specs/test_datafusion.py tests/unit_tests/db_engine_specs/test_base.py

parity:
    {{PY}} bench/parity.py --rows 1000 --out results/type-parity.json

golden-update: parity
    {{PY}} -c "import json,sys; sys.path[:0]=['tests','bench']; from test_type_parity import signature; json.dump(signature(json.load(open('results/type-parity.json'))), open('tests/golden/known_divergences.json','w'), indent=1)"

# All backends x paths, both downstreams (IPC and Superset's to_pandas_df).
bench:
    {{PY}} bench/run_bench.py --rows {{ROWS}} --rounds {{ROUNDS}} --max-rss-gb {{BENCH_MAX_RSS_GB}} --out results/bench-latest.json

# Large scale: Arrow path only, IPC downstream only (row paths need >10 GiB at 10M).
bench-large:
    {{PY}} bench/run_bench.py --rows {{LARGE_ROWS}} --rounds 3 3 --paths arrow --downstream ipc --max-rss-gb {{BENCH_MAX_RSS_GB}} --out results/bench-large-latest.json

# Fast sanity run (~2 min): 100k rows, 2 rounds.
bench-quick:
    {{PY}} bench/run_bench.py --rows 100000 --rounds 2 --out results/bench-quick.json
    {{PY}} bench/render.py results/bench-quick.json --out results/BENCH-quick.md

render main="results/bench-latest.json" large="results/bench-large-latest.json":
    {{PY}} bench/render.py {{main}} {{large}} --out BENCH.md

clean:
    rm -rf data .cache results/bench-latest.json results/bench-quick.json
