"""Base62 encoding/decoding and URL hashing."""

import hashlib


def base62_encode(n: int) -> str:
    """Encode integer to base62 string using [0-9a-zA-Z] alphabet."""
    if n == 0:
        return "0"

    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    result = []
    while n > 0:
        result.append(alphabet[n % 62])
        n //= 62
    return "".join(reversed(result))


def base62_decode(s: str) -> int:
    """Decode base62 string back to integer."""
    if not s:
        raise ValueError("empty string")

    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    result = 0
    for char in s:
        if char not in alphabet:
            raise ValueError(f"invalid base62 character: {char}")
        result = result * 62 + alphabet.index(char)
    return result


def hash_url(url: str) -> str:
    """Generate deterministic 6-char base62 hash from URL.

    Always produces same hash for same URL. URL variants (trailing slash)
    produce different hashes: http://a.com vs http://a.com/ differ.
    """
    digest = hashlib.sha256(url.encode()).digest()
    uint32 = int.from_bytes(digest[:4], byteorder="big")
    mod_value = uint32 % (62**6)
    encoded = base62_encode(mod_value)
    padded = encoded.rjust(6, "0")
    return padded
