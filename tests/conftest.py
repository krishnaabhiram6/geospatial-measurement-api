"""Pytest configuration: isolated DB, isolated upload dir, auto-generated fixtures."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make the project importable without installation.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """Point the app at a temp DB + temp upload dir for each test."""
    db_path = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("DEBUG", "false")

    # Re-import settings so the env changes take effect, and rebind the
    # database engine to the test database.
    import importlib

    import app.config as config_module
    importlib.reload(config_module)
    config_module.settings.upload_dir = upload_dir

    import app.database as db_module
    db_module.engine.dispose()
    db_module.engine = __import__("sqlalchemy").create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    db_module.SessionLocal.configure(bind=db_module.engine)
    db_module.init_db()

    yield {
        "db_path": db_path,
        "upload_dir": upload_dir,
    }

    db_module.engine.dispose()


@pytest.fixture()
def client(isolated_env):
    from fastapi.testclient import TestClient

    # Re-import the app so it picks up the reloaded settings/database.
    import importlib
    import app.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as c:
        yield c


@pytest.fixture(scope="session")
def fixtures_dir():
    return Path(__file__).resolve().parent / "data"


@pytest.fixture(scope="session")
def kml_bytes(fixtures_dir):
    path = fixtures_dir / "sample.kml"
    if not path.exists():
        _ensure_fixtures()
        path = fixtures_dir / "sample.kml"
    return path.read_bytes()


@pytest.fixture(scope="session")
def shapefile_zip_bytes(fixtures_dir):
    path = fixtures_dir / "sample_shapefile.zip"
    if not path.exists():
        _ensure_fixtures()
        path = fixtures_dir / "sample_shapefile.zip"
    return path.read_bytes()


def _ensure_fixtures() -> None:
    from tests import generate_fixtures

    generate_fixtures.main()
