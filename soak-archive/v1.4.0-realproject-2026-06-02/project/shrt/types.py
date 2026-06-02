"""Core types for shrt."""

import re
from dataclasses import dataclass
from typing import NewType

SCHEMA_VERSION = 1

ShortCode = NewType("ShortCode", str)
Timestamp = float


@dataclass
class Entry:
    """Storage entry for a shortened URL."""

    short_code: ShortCode
    url: str
    created: Timestamp
    version: int = SCHEMA_VERSION


def validate_short_code(code: str) -> None:
    """Validate short code format [a-zA-Z0-9_-]{1,32}.

    Permissive validation at storage layer; CLI will re-validate input.
    """
    if not code or len(code) > 32:
        raise ValueError(f"short code must be 1-32 characters (got {len(code)})")
    if not re.match(r"^[a-zA-Z0-9_-]+$", code):
        raise ValueError(
            f"short code must contain only alphanumeric, _, - (got {code!r})"
        )
