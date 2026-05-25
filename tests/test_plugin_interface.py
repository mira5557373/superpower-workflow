from __future__ import annotations

import pytest

from superpower_workflow.plugins.interface import Plugin, PluginVetoError


class TestPlugin:
    def test_default_name(self):
        p = Plugin()
        assert p.name == "unnamed"

    def test_default_version(self):
        p = Plugin()
        assert p.version == "0.0.0"

    def test_pre_phase_is_noop(self):
        p = Plugin()
        p.pre_phase("plan", {"name": "m1"})

    def test_post_phase_is_noop(self):
        p = Plugin()
        p.post_phase("plan", {"name": "m1"}, {"success": True})

    def test_pre_commit_is_noop(self):
        p = Plugin()
        p.pre_commit({"name": "m1"}, ["src/foo.py"])

    def test_post_milestone_is_noop(self):
        p = Plugin()
        p.post_milestone({"name": "m1"}, 5.0)


class TestPluginSubclass:
    def test_custom_plugin(self):
        class MyPlugin(Plugin):
            name = "my-plugin"
            version = "1.0.0"

            def __init__(self):
                self.phases_seen: list[str] = []

            def pre_phase(self, phase: str, milestone: dict) -> None:
                self.phases_seen.append(phase)

        p = MyPlugin()
        p.pre_phase("plan", {"name": "m1"})
        assert p.phases_seen == ["plan"]

    def test_veto_from_pre_phase(self):
        class VetoPlugin(Plugin):
            name = "veto"

            def pre_phase(self, phase: str, milestone: dict) -> None:
                raise PluginVetoError("Blocked by policy")

        p = VetoPlugin()
        with pytest.raises(PluginVetoError, match="Blocked by policy"):
            p.pre_phase("plan", {"name": "m1"})

    def test_veto_from_pre_commit(self):
        class VetoPlugin(Plugin):
            name = "veto"

            def pre_commit(self, milestone: dict, files: list[str]) -> None:
                if any("secrets" in f for f in files):
                    raise PluginVetoError("Cannot commit secrets")

        p = VetoPlugin()
        with pytest.raises(PluginVetoError, match="secrets"):
            p.pre_commit({"name": "m1"}, ["src/secrets.py"])


class TestPluginVetoError:
    def test_is_exception(self):
        assert issubclass(PluginVetoError, Exception)

    def test_message_preserved(self):
        e = PluginVetoError("test reason")
        assert str(e) == "test reason"
