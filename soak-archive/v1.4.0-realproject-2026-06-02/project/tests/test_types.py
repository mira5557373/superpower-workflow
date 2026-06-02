"""Test types and validation."""

import pytest

from shrt.types import SCHEMA_VERSION, Entry, ShortCode, validate_short_code


class TestEntry:
    """Test Entry dataclass."""

    def test_entry_creation(self):
        """Test creating an Entry with all fields."""
        entry = Entry(
            short_code=ShortCode("abc123"),
            url="https://example.com",
            created=1234567890.0,
        )
        assert entry.short_code == "abc123"
        assert entry.url == "https://example.com"
        assert entry.created == 1234567890.0
        assert entry.version == SCHEMA_VERSION

    def test_entry_version_defaults_to_schema_version(self):
        """Test Entry version field defaults to SCHEMA_VERSION."""
        entry = Entry(
            short_code=ShortCode("test"),
            url="https://test.com",
            created=1000.0,
        )
        assert entry.version == SCHEMA_VERSION

    def test_entry_version_can_be_set(self):
        """Test Entry version can be set explicitly."""
        entry = Entry(
            short_code=ShortCode("test"),
            url="https://test.com",
            created=1000.0,
            version=2,
        )
        assert entry.version == 2

    def test_entry_field_types(self):
        """Test Entry fields have correct types."""
        entry = Entry(
            short_code=ShortCode("abc"),
            url="https://a.com",
            created=1.0,
        )
        assert isinstance(entry.short_code, str)
        assert isinstance(entry.url, str)
        assert isinstance(entry.created, float)
        assert isinstance(entry.version, int)

    def test_entry_equality(self):
        """Test Entry equality comparison."""
        entry1 = Entry(
            short_code=ShortCode("test"),
            url="https://test.com",
            created=1.0,
        )
        entry2 = Entry(
            short_code=ShortCode("test"),
            url="https://test.com",
            created=1.0,
        )
        assert entry1 == entry2

    def test_entry_inequality(self):
        """Test Entry inequality when fields differ."""
        entry1 = Entry(
            short_code=ShortCode("test1"),
            url="https://test.com",
            created=1.0,
        )
        entry2 = Entry(
            short_code=ShortCode("test2"),
            url="https://test.com",
            created=1.0,
        )
        assert entry1 != entry2


class TestValidateShortCode:
    """Test short code validation."""

    def test_validate_single_char_lowercase(self):
        """Test single character lowercase is valid."""
        validate_short_code("a")  # Should not raise

    def test_validate_single_char_uppercase(self):
        """Test single character uppercase is valid."""
        validate_short_code("A")  # Should not raise

    def test_validate_single_digit(self):
        """Test single digit is valid."""
        validate_short_code("0")  # Should not raise

    def test_validate_hyphen(self):
        """Test hyphen is valid."""
        validate_short_code("-")  # Should not raise

    def test_validate_underscore(self):
        """Test underscore is valid."""
        validate_short_code("_")  # Should not raise

    def test_validate_mixed_alphanumeric(self):
        """Test mixed alphanumeric with hyphens and underscores."""
        validate_short_code("abc123_-XYZ")  # Should not raise

    def test_validate_32_chars_max(self):
        """Test 32 character code (maximum) is valid."""
        code = "a" * 32
        validate_short_code(code)  # Should not raise

    def test_validate_empty_string_invalid(self):
        """Test empty string is invalid."""
        with pytest.raises(ValueError):
            validate_short_code("")

    def test_validate_too_long_invalid(self):
        """Test code longer than 32 chars is invalid."""
        code = "a" * 33
        with pytest.raises(ValueError):
            validate_short_code(code)

    def test_validate_space_invalid(self):
        """Test space character is invalid."""
        with pytest.raises(ValueError):
            validate_short_code("abc 123")

    def test_validate_dot_invalid(self):
        """Test dot character is invalid."""
        with pytest.raises(ValueError):
            validate_short_code("abc.123")

    def test_validate_special_char_invalid(self):
        """Test special characters are invalid."""
        invalid_chars = ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")"]
        for char in invalid_chars:
            with pytest.raises(ValueError):
                validate_short_code(f"abc{char}123")
