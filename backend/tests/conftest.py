"""Test setup. Loads JSON fixtures and stubs out the firebase_admin module so
we don't need real credentials in CI."""

import json
import os
import sys
from pathlib import Path

import pytest

# Make `app.*` imports resolve when running pytest from anywhere.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name, "r") as f:
        return json.load(f)


@pytest.fixture
def uber_feed_19713():
    return load_fixture("uber_feed_19713.json")


@pytest.fixture
def uber_store_tacobell():
    return load_fixture("uber_store_tacobell.json")


@pytest.fixture(autouse=True)
def _stub_firestore(monkeypatch):
    """Force the firebase getter to return None so cache/track_popular_search
    short-circuit and we don't need real credentials."""
    from app.services import firebase_admin as fa
    monkeypatch.setattr(fa, "get_db", lambda: None)
