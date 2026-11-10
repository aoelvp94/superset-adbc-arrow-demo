#!/usr/bin/env bash
# Task A: verify whether apache-superset[datafusion] can be resolved.
# Writes resolver output + PyPI metadata into evidence/task-a/.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=evidence/task-a
SRC=${SUPERSET_SRC:-.cache/superset}
mkdir -p "$OUT"

pypi() { curl -fsS "https://pypi.org/pypi/$1/json"; }

pypi flightsql-dbapi | python3 -c "import json,sys;d=json.load(sys.stdin);i=d['info'];json.dump({'version':i['version'],'requires_dist':i['requires_dist'],'requires_python':i['requires_python'],'releases':{v:(f[0]['upload_time'] if f else None) for v,f in d['releases'].items()}},sys.stdout,indent=1)" > "$OUT/pypi-flightsql-dbapi.json"
pypi apache-superset | python3 -c "import json,sys;d=json.load(sys.stdin);i=d['info'];json.dump({'version':i['version'],'provides_extra':i['provides_extra'],'sqlalchemy_pins':[r for r in i['requires_dist'] if r.lower().startswith('sqlalchemy')]},sys.stdout,indent=1)" > "$OUT/pypi-apache-superset-latest.json"
pypi sqlalchemy-adbc | python3 -c "import json,sys;d=json.load(sys.stdin);i=d['info'];json.dump({'version':i['version'],'requires_dist':i['requires_dist'],'requires_python':i['requires_python']},sys.stdout,indent=1)" > "$OUT/pypi-sqlalchemy-adbc.json"

# 1) superset master pyproject (unpatched pins are identical; patch only adds an extra)
( cd "$SRC" && uv pip compile pyproject.toml --extra datafusion --python-version 3.11 --no-cache ) \
  > "$OUT/master-pyproject-extra-datafusion.txt" 2>&1; echo "exit=$?" >> "$OUT/master-pyproject-extra-datafusion.txt"

# 2) minimal: Superset master's sqlalchemy pin + the datafusion extra pin
printf 'sqlalchemy>=2.0.55,<2.1\nflightsql-dbapi>=0.2.2,<0.3\n' > /tmp/sab-minimal.in
uv pip compile /tmp/sab-minimal.in --python-version 3.11 --no-cache > "$OUT/minimal-sa2-plus-flightsql-dbapi.txt" 2>&1
echo "exit=$?" >> "$OUT/minimal-sa2-plus-flightsql-dbapi.txt"

# 3) latest PyPI release
LATEST=$(python3 -c "import json;print(json.load(open('$OUT/pypi-apache-superset-latest.json'))['version'])")
echo "apache-superset[datafusion]==$LATEST" > /tmp/sab-pypi.in
uv pip compile /tmp/sab-pypi.in --python-version 3.11 --no-cache > "$OUT/pypi-latest-extra-datafusion.txt" 2>&1
echo "exit=$?" >> "$OUT/pypi-latest-extra-datafusion.txt"

# 4) sqlalchemy-adbc on Superset's minimum Python
echo "sqlalchemy-adbc[flightsql]>=0.9.5" > /tmp/sab-sqa.in
uv pip compile /tmp/sab-sqa.in --python-version 3.11 --no-cache > "$OUT/sqlalchemy-adbc-py311.txt" 2>&1
echo "exit=$?" >> "$OUT/sqlalchemy-adbc-py311.txt"

for f in master-pyproject-extra-datafusion minimal-sa2-plus-flightsql-dbapi pypi-latest-extra-datafusion sqlalchemy-adbc-py311; do
  echo "== $f"; grep -E "error|cause|because|warning|exit=" "$OUT/$f.txt" | head -6
done
