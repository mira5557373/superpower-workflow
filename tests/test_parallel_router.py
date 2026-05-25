from __future__ import annotations

from superpower_workflow.parallel.router import (
    ModelRouter,
    RoutingRule,
    score_complexity,
)


class TestScoreComplexity:
    def test_simple_milestone(self):
        ms = {"name": "m1", "description": "fix typo in readme"}
        score = score_complexity(ms)
        assert 0.0 <= score.value <= 0.3

    def test_complex_milestone_with_architecture_keyword(self):
        ms = {
            "name": "m1",
            "description": "refactor authentication architecture with new middleware",
        }
        score = score_complexity(ms)
        assert score.value >= 0.5

    def test_high_file_count_raises_score(self):
        ms = {
            "name": "m1",
            "description": "update styles",
            "spec_sections": "a,b,c,d,e,f,g,h,i,j",
        }
        score = score_complexity(ms)
        score_few = score_complexity(
            {"name": "m2", "description": "update styles", "spec_sections": "a"}
        )
        assert score.value > score_few.value

    def test_new_module_keyword_raises_score(self):
        ms = {"name": "m1", "description": "add new parallel execution module"}
        score = score_complexity(ms)
        assert score.value >= 0.4

    def test_manual_override_in_milestone(self):
        ms = {"name": "m1", "description": "simple fix", "complexity_override": 0.9}
        score = score_complexity(ms)
        assert score.value == 0.9

    def test_score_bounds(self):
        ms = {"name": "m1", "description": ""}
        score = score_complexity(ms)
        assert 0.0 <= score.value <= 1.0

    def test_depends_on_adds_to_score(self):
        ms = {
            "name": "m1",
            "description": "update handler",
            "depends_on": ["m0a", "m0b", "m0c"],
        }
        score_with_deps = score_complexity(ms)
        score_no_deps = score_complexity({"name": "m1", "description": "update handler"})
        assert score_with_deps.value >= score_no_deps.value

    def test_complexity_score_signals_populated(self):
        ms = {
            "name": "m1",
            "description": "refactor database layer and add migration system",
            "spec_sections": "4.1,4.2,4.3",
        }
        score = score_complexity(ms)
        assert len(score.signals) > 0
        assert isinstance(score.signals, list)


class TestModelRouter:
    def test_routes_high_complexity_to_opus(self):
        rules = [
            RoutingRule(threshold=0.7, model="opus"),
            RoutingRule(threshold=0.3, model="sonnet"),
            RoutingRule(threshold=0.0, model="haiku"),
        ]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "refactor authentication architecture with migration"}
        decision = router.route(ms)
        assert decision.model == "opus"

    def test_routes_low_complexity_to_haiku(self):
        rules = [
            RoutingRule(threshold=0.7, model="opus"),
            RoutingRule(threshold=0.3, model="sonnet"),
            RoutingRule(threshold=0.0, model="haiku"),
        ]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "fix typo"}
        decision = router.route(ms)
        assert decision.model == "haiku"

    def test_routes_medium_complexity_to_sonnet(self):
        rules = [
            RoutingRule(threshold=0.7, model="opus"),
            RoutingRule(threshold=0.3, model="sonnet"),
            RoutingRule(threshold=0.0, model="haiku"),
        ]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "add new integration module for the api pipeline"}
        decision = router.route(ms)
        assert decision.model == "sonnet"

    def test_milestone_override_takes_precedence(self):
        rules = [RoutingRule(threshold=0.0, model="haiku")]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "fix typo", "model_override": "opus"}
        decision = router.route(ms)
        assert decision.model == "opus"
        assert "override" in decision.reason

    def test_default_model_when_no_rules(self):
        router = ModelRouter(rules=[], default_model="sonnet")
        ms = {"name": "m1", "description": "something"}
        decision = router.route(ms)
        assert decision.model == "sonnet"

    def test_from_config_disabled_returns_default(self):
        config = {"model": "opus", "model_routing": {"enabled": False}}
        router = ModelRouter.from_config(config)
        ms = {"name": "m1", "description": "complex refactor architecture migration"}
        decision = router.route(ms)
        assert decision.model == "opus"

    def test_from_config_enabled_applies_rules(self):
        config = {
            "model": "opus",
            "model_routing": {
                "enabled": True,
                "default_model": "opus",
                "rules": [
                    {"threshold": 0.7, "model": "opus"},
                    {"threshold": 0.0, "model": "haiku"},
                ],
            },
        }
        router = ModelRouter.from_config(config)
        ms = {"name": "m1", "description": "fix typo"}
        decision = router.route(ms)
        assert decision.model == "haiku"

    def test_route_decision_includes_complexity(self):
        rules = [RoutingRule(threshold=0.0, model="haiku")]
        router = ModelRouter(rules)
        ms = {"name": "m1", "description": "refactor database module"}
        decision = router.route(ms)
        assert decision.complexity.value > 0
        assert len(decision.complexity.signals) > 0

    def test_from_config_no_routing_key(self):
        config = {"model": "sonnet"}
        router = ModelRouter.from_config(config)
        decision = router.route({"name": "m1", "description": "anything"})
        assert decision.model == "sonnet"
