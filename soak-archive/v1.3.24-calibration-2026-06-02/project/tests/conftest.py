from __future__ import annotations

import pytest


@pytest.fixture
def tmp_home(tmp_path):
    """Fixture that provides a temporary HOME directory."""
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def tmp_store_path(tmp_home, monkeypatch):
    """Fixture that provides a temporary store path and monkeypatches HOME."""
    monkeypatch.setenv("HOME", str(tmp_home))
    store_dir = tmp_home / ".todo"
    store_path = store_dir / "store.json"
    return store_path


@pytest.fixture
def clean_store(tmp_store_path):
    """Fixture that cleans up store after each test."""
    import contextlib

    yield tmp_store_path
    # Clean up if it exists
    if tmp_store_path.exists():
        tmp_store_path.unlink()
    if tmp_store_path.parent.exists():
        with contextlib.suppress(OSError):
            tmp_store_path.parent.rmdir()
