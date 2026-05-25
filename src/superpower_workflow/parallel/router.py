from __future__ import annotations

import re
from dataclasses import dataclass, field

COMPLEXITY_KEYWORDS_HIGH = frozenset(
    {
        "refactor",
        "architecture",
        "redesign",
        "migration",
        "parallel",
        "concurrent",
        "security",
        "authentication",
    }
)

COMPLEXITY_KEYWORDS_MEDIUM = frozenset(
    {
        "module",
        "package",
        "integration",
        "pipeline",
        "database",
        "cache",
        "queue",
        "api",
    }
)


@dataclass
class ComplexityScore:
    value: float = 0.0
    signals: list[str] = field(default_factory=list)


@dataclass
class RoutingRule:
    threshold: float
    model: str


@dataclass
class RouteDecision:
    model: str
    complexity: ComplexityScore
    reason: str = ""


def score_complexity(ms: dict) -> ComplexityScore:
    override = ms.get("complexity_override")
    if override is not None:
        return ComplexityScore(
            value=float(override),
            signals=["manual_override"],
        )

    signals: list[str] = []
    value = 0.0

    desc = ms.get("description", "").lower()
    words = set(re.findall(r"\w+", desc))

    high_matches = words & COMPLEXITY_KEYWORDS_HIGH
    if high_matches:
        value += 0.2 * len(high_matches)
        signals.append(f"high_keywords:{','.join(sorted(high_matches))}")

    med_matches = words & COMPLEXITY_KEYWORDS_MEDIUM
    if med_matches:
        value += 0.1 * len(med_matches)
        signals.append(f"medium_keywords:{','.join(sorted(med_matches))}")

    sections = ms.get("spec_sections", "")
    if isinstance(sections, list):
        section_count = len(sections)
    else:
        section_count = len([s for s in sections.split(",") if s.strip()]) if sections else 0
    if section_count > 5:
        value += 0.15
        signals.append(f"many_sections:{section_count}")
    elif section_count > 2:
        value += 0.08
        signals.append(f"some_sections:{section_count}")

    deps = ms.get("depends_on", [])
    if len(deps) >= 3:
        value += 0.1
        signals.append(f"many_deps:{len(deps)}")
    elif len(deps) >= 1:
        value += 0.05
        signals.append(f"has_deps:{len(deps)}")

    if any(kw in desc for kw in ("add new", "new module", "new package")):
        value += 0.1
        signals.append("new_module")

    value = max(0.0, min(1.0, value))
    return ComplexityScore(value=value, signals=signals)


class ModelRouter:
    def __init__(
        self,
        rules: list[RoutingRule],
        default_model: str = "opus",
    ) -> None:
        self._rules = sorted(rules, key=lambda r: r.threshold, reverse=True)
        self._default = default_model

    def route(self, ms: dict) -> RouteDecision:
        override = ms.get("model_override")
        if override:
            return RouteDecision(
                model=override,
                complexity=ComplexityScore(value=0.0, signals=["model_override"]),
                reason=f"milestone override: {override}",
            )
        complexity = score_complexity(ms)
        for rule in self._rules:
            if complexity.value >= rule.threshold:
                return RouteDecision(
                    model=rule.model,
                    complexity=complexity,
                    reason=f"score {complexity.value:.2f} >= threshold {rule.threshold}",
                )
        return RouteDecision(
            model=self._default,
            complexity=complexity,
            reason=f"below all thresholds, using default: {self._default}",
        )

    @classmethod
    def from_config(cls, config: dict) -> ModelRouter:
        routing = config.get("model_routing", {})
        if not routing.get("enabled", False):
            default = config.get("model", "opus")
            return cls(rules=[], default_model=default)
        rules = [
            RoutingRule(threshold=r["threshold"], model=r["model"])
            for r in routing.get("rules", [])
        ]
        return cls(
            rules=rules,
            default_model=routing.get("default_model", config.get("model", "opus")),
        )
