from __future__ import annotations

from unittest.mock import MagicMock, patch

from superpower_workflow.plugins.interface import Plugin
from superpower_workflow.plugins.loader import ENTRY_POINT_GROUP, load_plugins


class _TestPlugin(Plugin):
    name = "test-plugin"
    version = "1.0.0"


class _BadPlugin:
    """Not a Plugin subclass."""

    name = "bad"


class TestLoadPlugins:
    def test_loads_valid_plugin(self):
        ep = MagicMock()
        ep.load.return_value = _TestPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "test-plugin"

    def test_skips_non_plugin_class(self):
        ep = MagicMock()
        ep.load.return_value = _BadPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins()
        assert len(plugins) == 0

    def test_skips_broken_entry_point(self):
        ep = MagicMock()
        ep.load.side_effect = ImportError("missing module")
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins()
        assert len(plugins) == 0

    def test_loads_multiple_plugins(self):
        ep1 = MagicMock()
        ep1.load.return_value = _TestPlugin
        ep2 = MagicMock()
        ep2.load.return_value = _TestPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep1, ep2]):
            plugins = load_plugins()
        assert len(plugins) == 2

    def test_uses_correct_entry_point_group(self):
        assert ENTRY_POINT_GROUP == "superpower_workflow.plugins"

    def test_filters_blocked_plugins(self):
        ep = MagicMock()
        ep.load.return_value = _TestPlugin
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[ep]):
            plugins = load_plugins(blocked=["test-plugin"])
        assert len(plugins) == 0

    def test_empty_when_no_entry_points(self):
        with patch("superpower_workflow.plugins.loader.entry_points", return_value=[]):
            plugins = load_plugins()
        assert plugins == []
