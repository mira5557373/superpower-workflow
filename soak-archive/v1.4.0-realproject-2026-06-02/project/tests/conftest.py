"""Shared pytest fixtures."""

import time

import pytest


@pytest.fixture
def sample_entry():
    """Return a valid Entry-like dict for testing."""
    return {
        "short_code": "abc123",
        "url": "https://example.com",
        "created": time.time(),
        "version": 1,
    }


@pytest.fixture
def sample_urls():
    """Return list of valid http/https URLs."""
    return [
        "http://example.com",
        "https://example.com",
        "https://example.com/path/to/page",
        "https://example.com?query=value",
        "https://example.com:8080/path",
    ]
