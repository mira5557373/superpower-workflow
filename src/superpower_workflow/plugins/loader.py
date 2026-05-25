from __future__ import annotations

from importlib.metadata import entry_points

from superpower_workflow.plugins.interface import Plugin

ENTRY_POINT_GROUP = "superpower_workflow.plugins"


def load_plugins(blocked: list[str] | None = None) -> list[Plugin]:
    blocked_set = set(blocked or [])
    plugins: list[Plugin] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            instance = cls()
            if isinstance(instance, Plugin) and instance.name not in blocked_set:
                plugins.append(instance)
        except Exception:
            continue
    return plugins
