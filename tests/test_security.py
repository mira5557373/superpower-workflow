from __future__ import annotations

import os
from unittest.mock import patch

from superpower_workflow.security import SecretsHandler


class TestSecretsHandlerResolve:
    def test_resolve_all_present(self):
        config = {"db_password": "DB_PASSWORD", "api_key": "API_KEY"}
        with patch.dict(os.environ, {"DB_PASSWORD": "secret1", "API_KEY": "secret2"}):
            handler = SecretsHandler(config)
            handler.resolve()

    def test_resolve_missing_env_var_raises(self):
        config = {"db_password": "MISSING_VAR"}
        with patch.dict(os.environ, {}, clear=True):
            handler = SecretsHandler(config)
            try:
                handler.resolve()
                raise AssertionError("Should have raised")
            except ValueError as e:
                assert "MISSING_VAR" in str(e)

    def test_resolve_empty_config(self):
        handler = SecretsHandler({})
        handler.resolve()

    def test_resolve_partial_missing(self):
        config = {"a": "A_VAR", "b": "B_VAR"}
        with patch.dict(os.environ, {"A_VAR": "val"}, clear=True):
            handler = SecretsHandler(config)
            try:
                handler.resolve()
                raise AssertionError("Should have raised")
            except ValueError as e:
                assert "B_VAR" in str(e)


class TestSecretsHandlerPromptFragment:
    def test_generates_fragment_for_each_secret(self):
        config = {"db_password": "DB_PASSWORD", "api_key": "API_KEY"}
        with patch.dict(os.environ, {"DB_PASSWORD": "s1", "API_KEY": "s2"}):
            handler = SecretsHandler(config)
            fragment = handler.prompt_fragment()
        assert "db_password" in fragment
        assert "$DB_PASSWORD" in fragment
        assert "api_key" in fragment
        assert "$API_KEY" in fragment

    def test_fragment_contains_never_hardcode(self):
        config = {"token": "TOKEN_VAR"}
        with patch.dict(os.environ, {"TOKEN_VAR": "abc"}):
            handler = SecretsHandler(config)
            fragment = handler.prompt_fragment()
        assert "NEVER" in fragment

    def test_actual_values_not_in_fragment(self):
        config = {"token": "TOKEN_VAR"}
        with patch.dict(os.environ, {"TOKEN_VAR": "super-secret-value-123"}):
            handler = SecretsHandler(config)
            fragment = handler.prompt_fragment()
        assert "super-secret-value-123" not in fragment

    def test_empty_config_returns_empty(self):
        handler = SecretsHandler({})
        assert handler.prompt_fragment() == ""


class TestSecretsHandlerRedact:
    def test_redacts_secret_values(self):
        config = {"db_password": "DB_PASSWORD"}
        with patch.dict(os.environ, {"DB_PASSWORD": "hunter2"}):
            handler = SecretsHandler(config)
            handler.resolve()
            result = handler.redact("password is hunter2 in config")
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_redacts_multiple_secrets(self):
        config = {"a": "A_VAR", "b": "B_VAR"}
        with patch.dict(os.environ, {"A_VAR": "alpha", "B_VAR": "beta"}):
            handler = SecretsHandler(config)
            handler.resolve()
            result = handler.redact("alpha and beta values")
        assert "alpha" not in result
        assert "beta" not in result

    def test_no_secrets_returns_unchanged(self):
        handler = SecretsHandler({})
        assert handler.redact("some text") == "some text"

    def test_redact_before_resolve_is_safe(self):
        config = {"token": "TOKEN"}
        with patch.dict(os.environ, {"TOKEN": "abc"}):
            handler = SecretsHandler(config)
            result = handler.redact("abc text")
        assert result == "abc text"
