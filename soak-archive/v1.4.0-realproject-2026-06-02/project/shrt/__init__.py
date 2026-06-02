"""shrt — Minimal URL shortener."""

from shrt.exceptions import (
    StorageCorruptedError,
    StorageError,
    StorageIOError,
    StorageNotFoundError,
    StoragePermissionError,
)
from shrt.hash import base62_decode, base62_encode, hash_url
from shrt.types import SCHEMA_VERSION, Entry, ShortCode, validate_short_code

__all__ = [
    "Entry",
    "ShortCode",
    "SCHEMA_VERSION",
    "validate_short_code",
    "hash_url",
    "base62_encode",
    "base62_decode",
    "StorageError",
    "StorageNotFoundError",
    "StorageIOError",
    "StorageCorruptedError",
    "StoragePermissionError",
]
