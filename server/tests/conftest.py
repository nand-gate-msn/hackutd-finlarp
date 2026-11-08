import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Every test gets fresh SQLite files."""
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "work.db"))
    monkeypatch.setattr(settings, "private_db_path", str(tmp_path / "private.db"))
