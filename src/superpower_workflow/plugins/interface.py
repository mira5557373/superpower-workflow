from __future__ import annotations


class PluginVetoError(Exception):
    """Raised by a plugin to block execution at a lifecycle hook."""


class Plugin:
    name: str = "unnamed"
    version: str = "0.0.0"

    def pre_phase(self, phase: str, milestone: dict) -> None:
        pass

    def post_phase(self, phase: str, milestone: dict, result: dict) -> None:
        pass

    def pre_commit(self, milestone: dict, files: list[str]) -> None:
        pass

    def post_milestone(self, milestone: dict, cost: float) -> None:
        pass
