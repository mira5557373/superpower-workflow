"""End-to-end integration test for p1-m1 milestone."""

import pytest

from shrt import (
    SCHEMA_VERSION,
    Entry,
    ShortCode,
    base62_decode,
    base62_encode,
    hash_url,
    validate_short_code,
)


def test_e2e_full_flow():
    """Test complete milestone flow: hash, validate, entry, storage."""
    url = "https://example.com/path"

    # Generate hash for URL
    hashed = hash_url(url)
    assert len(hashed) == 6
    assert all(
        c in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for c in hashed
    )

    # Validate the short code
    validate_short_code(hashed)  # Should not raise

    # Create Entry with hashed code
    entry = Entry(
        short_code=ShortCode(hashed),
        url=url,
        created=1000.0,
    )
    assert entry.short_code == hashed
    assert entry.url == url
    assert entry.created == 1000.0
    assert entry.version == SCHEMA_VERSION

    # Simulate storage in dict
    storage = {}
    storage[entry.short_code] = entry

    # Retrieve and verify
    retrieved = storage[hashed]
    assert retrieved.short_code == hashed
    assert retrieved.url == url
    assert retrieved.version == SCHEMA_VERSION


def test_e2e_round_trip_base62():
    """Test round-trip base62 encoding/decoding."""
    test_values = [0, 1, 10, 35, 36, 61, 62, 1000, 3843, 999999]
    for value in test_values:
        encoded = base62_encode(value)
        decoded = base62_decode(encoded)
        assert decoded == value


def test_e2e_url_hash_determinism():
    """Test URL hashing determinism and consistency."""
    urls = [
        "https://example.com",
        "https://example.com/",
        "https://example.com/path",
        "http://a.com",
        "http://b.com",
    ]

    hashes = {}
    for url in urls:
        # Hash same URL twice, should get same result
        h1 = hash_url(url)
        h2 = hash_url(url)
        assert h1 == h2, f"Hash mismatch for {url}"
        hashes[url] = h1

    # Different URLs should produce different hashes
    assert hashes["https://example.com"] != hashes["https://example.com/"]
    assert hashes["http://a.com"] != hashes["http://b.com"]


def test_e2e_entry_with_schema_version():
    """Test Entry schema version is always SCHEMA_VERSION."""
    entry1 = Entry(
        short_code=ShortCode("test1"),
        url="https://test1.com",
        created=1.0,
    )
    entry2 = Entry(
        short_code=ShortCode("test2"),
        url="https://test2.com",
        created=2.0,
        version=2,
    )

    # Default should use SCHEMA_VERSION
    assert entry1.version == SCHEMA_VERSION
    # Explicit version can be set but we verify it's tracked
    assert entry2.version == 2
    # SCHEMA_VERSION constant should be 1
    assert SCHEMA_VERSION == 1


def test_e2e_short_code_validation_scope():
    """Test validation permissiveness and boundary cases."""
    # Valid cases
    valid_codes = [
        "a",
        "A",
        "0",
        "_",
        "-",
        "abc123_-XYZ",
        "a" * 32,
    ]
    for code in valid_codes:
        validate_short_code(code)  # Should not raise

    # Invalid cases
    invalid_codes = [
        "",
        "a" * 33,
        "abc 123",
        "abc.123",
        "abc@123",
    ]
    for code in invalid_codes:
        with pytest.raises(ValueError):
            validate_short_code(code)
