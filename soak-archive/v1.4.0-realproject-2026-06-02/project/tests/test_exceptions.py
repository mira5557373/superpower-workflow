"""Test exception hierarchy."""

from shrt.exceptions import (
    StorageCorruptedError,
    StorageError,
    StorageIOError,
    StorageNotFoundError,
    StoragePermissionError,
)


def test_storage_error_base_instantiation():
    """Test StorageError can be instantiated."""
    exc = StorageError("test error")
    assert str(exc) == "test error"
    assert isinstance(exc, Exception)


def test_storage_error_repr():
    """Test StorageError repr."""
    exc = StorageError("test")
    assert "StorageError" in repr(exc)


def test_storage_not_found_error_inheritance():
    """Test StorageNotFoundError inherits from StorageError."""
    exc = StorageNotFoundError("file not found")
    assert isinstance(exc, StorageError)
    assert isinstance(exc, Exception)
    assert str(exc) == "file not found"


def test_storage_io_error_inheritance():
    """Test StorageIOError inherits from StorageError."""
    exc = StorageIOError("disk error")
    assert isinstance(exc, StorageError)
    assert isinstance(exc, Exception)
    assert str(exc) == "disk error"


def test_storage_corrupted_error_inheritance():
    """Test StorageCorruptedError inherits from StorageError."""
    exc = StorageCorruptedError("invalid json")
    assert isinstance(exc, StorageError)
    assert isinstance(exc, Exception)
    assert str(exc) == "invalid json"


def test_storage_permission_error_inheritance():
    """Test StoragePermissionError inherits from StorageError."""
    exc = StoragePermissionError("access denied")
    assert isinstance(exc, StorageError)
    assert isinstance(exc, Exception)
    assert str(exc) == "access denied"


def test_all_exceptions_inherit_from_storage_error():
    """Test all custom exceptions inherit from StorageError."""
    exc_classes = [
        StorageNotFoundError,
        StorageIOError,
        StorageCorruptedError,
        StoragePermissionError,
    ]
    for exc_class in exc_classes:
        assert issubclass(exc_class, StorageError)
