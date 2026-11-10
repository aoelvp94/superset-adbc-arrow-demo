# Minimal Superset config used only to import SupersetResultSet in-process.
SECRET_KEY = "local-bench-only-not-a-secret"
SQLALCHEMY_DATABASE_URI = "sqlite:////tmp/superset-bench-meta.db"
