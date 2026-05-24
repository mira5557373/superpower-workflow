from __future__ import annotations

import os


class SecretsHandler:
    def __init__(self, config: dict) -> None:
        self._config = config
        self._resolved: dict[str, str] = {}

    def resolve(self) -> None:
        missing = []
        for logical_name, env_var in self._config.items():
            val = os.environ.get(env_var, "")
            if not val:
                missing.append(env_var)
            else:
                self._resolved[logical_name] = val
        if missing:
            raise ValueError(f"Missing required env vars for secrets: {', '.join(missing)}")

    def prompt_fragment(self) -> str:
        if not self._config:
            return ""
        lines = []
        for logical_name, env_var in self._config.items():
            lines.append(f"Secret {logical_name} is in env var ${env_var}.")
        lines.append("Use env vars in code. NEVER hardcode secret values.")
        return "\n".join(lines)

    def redact(self, text: str) -> str:
        for value in self._resolved.values():
            if value:
                text = text.replace(value, "[REDACTED]")
        return text
