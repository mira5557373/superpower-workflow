"""Exception hierarchy for shrt storage operations."""


class StorageError(Exception):
    """Base exception for all storage-related errors."""

    pass


class StorageNotFoundError(StorageError):
    """File or resource doesn't exist."""

    pass


class StorageIOError(StorageError):
    """Disk I/O failure."""

    pass


class StorageCorruptedError(StorageError):
    """Invalid JSON or schema mismatch."""

    pass


class StoragePermissionError(StorageError):
    """Access denied."""

    pass
