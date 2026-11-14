# GizmoSQL (Arrow Flight SQL server on DuckDB), pinned by digest, plus the
# DuckDB json extension. The upstream image does not bundle json and its
# runtime autoload uses plain http, which fails in some sandboxes, so we
# fetch the signed extension over https at build time.
FROM gizmodata/gizmosql@sha256:4f719de2c2cef4bd80052d54020141e523bd74999a615cdfdf1624f2374d5ccf
ARG DUCKDB_VERSION=v1.5.6
# The image is multi-arch, so take the platform from DuckDB itself.
RUN python3 -c "import duckdb,gzip,urllib.request,os; \
p=duckdb.execute('PRAGMA platform').fetchone()[0]; \
u=f'https://extensions.duckdb.org/${DUCKDB_VERSION}/{p}/json.duckdb_extension.gz'; \
d=os.path.expanduser(f'~/.duckdb/extensions/${DUCKDB_VERSION}/{p}'); \
os.makedirs(d, exist_ok=True); \
r=urllib.request.Request(u, headers={'User-Agent': 'DuckDB'}); \
open(os.path.join(d, 'json.duckdb_extension'),'wb').write(gzip.decompress(urllib.request.urlopen(r).read()))"
