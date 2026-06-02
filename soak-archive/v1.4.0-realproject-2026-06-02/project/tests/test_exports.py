"""Test package exports."""

import shrt


def test_all_exports_present():
    """Test __all__ is defined and non-empty."""
    assert hasattr(shrt, "__all__")
    assert len(shrt.__all__) > 0


def test_entry_exported():
    """Test Entry is exported."""
    assert hasattr(shrt, "Entry")
    assert shrt.Entry is not None


def test_short_code_exported():
    """Test ShortCode is exported."""
    assert hasattr(shrt, "ShortCode")
    assert shrt.ShortCode is not None


def test_schema_version_exported():
    """Test SCHEMA_VERSION is exported."""
    assert hasattr(shrt, "SCHEMA_VERSION")
    assert isinstance(shrt.SCHEMA_VERSION, int)


def test_validate_short_code_exported():
    """Test validate_short_code is exported."""
    assert hasattr(shrt, "validate_short_code")
    assert callable(shrt.validate_short_code)


def test_hash_url_exported():
    """Test hash_url is exported."""
    assert hasattr(shrt, "hash_url")
    assert callable(shrt.hash_url)


def test_base62_encode_exported():
    """Test base62_encode is exported."""
    assert hasattr(shrt, "base62_encode")
    assert callable(shrt.base62_encode)


def test_base62_decode_exported():
    """Test base62_decode is exported."""
    assert hasattr(shrt, "base62_decode")
    assert callable(shrt.base62_decode)


def test_storage_error_exported():
    """Test StorageError is exported."""
    assert hasattr(shrt, "StorageError")
    assert shrt.StorageError is not None


def test_storage_not_found_error_exported():
    """Test StorageNotFoundError is exported."""
    assert hasattr(shrt, "StorageNotFoundError")
    assert shrt.StorageNotFoundError is not None


def test_storage_io_error_exported():
    """Test StorageIOError is exported."""
    assert hasattr(shrt, "StorageIOError")
    assert shrt.StorageIOError is not None


def test_storage_corrupted_error_exported():
    """Test StorageCorruptedError is exported."""
    assert hasattr(shrt, "StorageCorruptedError")
    assert shrt.StorageCorruptedError is not None


def test_storage_permission_error_exported():
    """Test StoragePermissionError is exported."""
    assert hasattr(shrt, "StoragePermissionError")
    assert shrt.StoragePermissionError is not None


def test_all_exports_are_importable_from_root():
    """Test all __all__ exports are importable from shrt root."""
    for name in shrt.__all__:
        assert hasattr(shrt, name), f"{name} in __all__ but not exported"
