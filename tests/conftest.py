"""
conftest.py - Shared set-up for the automated tests
===================================================

* Puts the project folder on the import path so `import app...` works when
  running `python -m pytest` from the project folder.
* Points DNS_REPORTS_DATA_DIR at a temporary folder for every test, so the
  tests can never read or change the real database.
* `repo` fixture: a MastersRepo on a fresh in-memory database.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.database import connect            # noqa: E402
from app.data.masters_repo import MastersRepo    # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DNS_REPORTS_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def repo():
    return MastersRepo(connect(":memory:"))
