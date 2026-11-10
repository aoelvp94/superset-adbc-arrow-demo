import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))


@pytest.fixture(scope="session")
def superset_ctx():
    import common

    app = common.superset_app()
    with app.app_context():
        yield app
