"""Test base62 encoding and decoding."""

import pytest

from shrt.hash import base62_decode, base62_encode, hash_url

BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


class TestBase62Encode:
    """Test base62_encode function."""

    def test_encode_single_digits_0_to_9(self):
        """Test encoding digits 0-9 map to characters 0-9."""
        for i in range(10):
            assert base62_encode(i) == str(i)

    def test_encode_10_to_35_map_to_a_to_z(self):
        """Test encoding 10-35 map to characters a-z."""
        assert base62_encode(10) == "a"
        assert base62_encode(35) == "z"

    def test_encode_36_to_61_map_to_uppercase_a_to_z(self):
        """Test encoding 36-61 map to characters A-Z."""
        assert base62_encode(36) == "A"
        assert base62_encode(61) == "Z"

    def test_encode_zero(self):
        """Test encoding zero."""
        assert base62_encode(0) == "0"

    def test_encode_62_equals_10(self):
        """Test encoding 62 produces 10 (two-digit base62)."""
        assert base62_encode(62) == "10"

    def test_encode_3843_equals_ZZ(self):
        """Test encoding 3843 produces ZZ (uppercase)."""
        assert base62_encode(3843) == "ZZ"

    def test_encode_large_number(self):
        """Test encoding a large number."""
        result = base62_encode(56800235584)  # A large base62 number
        assert isinstance(result, str)
        assert len(result) > 0
        assert all(c in BASE62_CHARS for c in result)


class TestBase62Decode:
    """Test base62_decode function."""

    def test_decode_single_digits(self):
        """Test decoding single digits."""
        for i in range(10):
            assert base62_decode(str(i)) == i

    def test_decode_lowercase_letters(self):
        """Test decoding lowercase letters."""
        assert base62_decode("a") == 10
        assert base62_decode("z") == 35

    def test_decode_uppercase_letters(self):
        """Test decoding uppercase letters."""
        assert base62_decode("A") == 36
        assert base62_decode("Z") == 61

    def test_decode_10_equals_62(self):
        """Test decoding 10 produces 62."""
        assert base62_decode("10") == 62

    def test_decode_ZZ_equals_3843(self):
        """Test decoding ZZ produces 3843."""
        assert base62_decode("ZZ") == 3843

    def test_decode_invalid_char_raises_value_error(self):
        """Test decoding invalid characters raises ValueError."""
        with pytest.raises(ValueError):
            base62_decode("!")
        with pytest.raises(ValueError):
            base62_decode("@")
        with pytest.raises(ValueError):
            base62_decode("_")

    def test_decode_empty_string_raises_value_error(self):
        """Test decoding empty string raises ValueError."""
        with pytest.raises(ValueError):
            base62_decode("")

    def test_decode_round_trip(self):
        """Test encoding then decoding returns original value."""
        for i in [0, 1, 10, 35, 36, 61, 62, 3843, 1000000]:
            encoded = base62_encode(i)
            decoded = base62_decode(encoded)
            assert decoded == i


class TestHashUrl:
    """Test hash_url function."""

    def test_hash_url_is_deterministic(self):
        """Test hash_url produces same result for same input."""
        url = "https://example.com"
        result1 = hash_url(url)
        result2 = hash_url(url)
        assert result1 == result2

    def test_hash_url_produces_6_char_base62(self):
        """Test hash_url produces exactly 6 character base62 string."""
        url = "https://example.com"
        result = hash_url(url)
        assert len(result) == 6
        assert all(c in BASE62_CHARS for c in result)

    def test_hash_url_different_urls_different_hashes(self):
        """Test different URLs produce different hashes."""
        url1 = "https://a.com"
        url2 = "https://b.com"
        assert hash_url(url1) != hash_url(url2)

    def test_hash_url_trailing_slash_matters(self):
        """Test URL variants with trailing slashes produce different hashes."""
        url1 = "http://a.com"
        url2 = "http://a.com/"
        assert hash_url(url1) != hash_url(url2)

    def test_hash_url_with_sample_urls(self, sample_urls):
        """Test hash_url on all sample URLs from fixture."""
        for url in sample_urls:
            result = hash_url(url)
            assert len(result) == 6
            assert all(c in BASE62_CHARS for c in result)
