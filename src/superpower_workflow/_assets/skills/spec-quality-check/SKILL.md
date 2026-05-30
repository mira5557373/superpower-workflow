---
name: spec-quality-check
description: Review a spec.md file for quality issues that will degrade sw run output. Use when a user wants a deeper review than `sw lint-spec` provides — this looks for semantic issues like vague requirements, implicit assumptions, missing acceptance criteria.
keywords: spec, requirements, quality, lint, review
triggers:
  - "/sw-spec-check"
  - "review my spec"
  - "is this spec good"
---

# Spec quality check

You are reviewing a spec for use with `sw decompose` and `sw run`.

## Instructions

1. **Read the spec file** at the path provided.
2. **Run `sw lint-spec PATH`** first (it's zero-LLM rule-based — catches structural issues for free). Capture the score and warnings.
3. **Then layer semantic review on top.** Look for:
   - **Vague verbs**: "handle", "manage", "process" without saying HOW. Ask: what's the observable behavior?
   - **Implicit assumptions**: "obviously", "of course", "standard X". Make them explicit.
   - **Missing acceptance criteria**: every functional requirement needs a "done when" condition.
   - **Hidden non-functional requirements**: latency, security, audit, compatibility that the user didn't think to spell out.
   - **Mixed concerns**: one numbered requirement covering 3 features → suggest splitting.
   - **Over-specification**: implementation details mixed in with requirements → flag and recommend moving to a separate doc.
4. **Output a structured review** — sections: Strengths / Vague / Missing AC / Hidden NFRs / Suggested rewrites. Score each suggested fix as **High** / **Medium** / **Low** impact.

## Output schema

```json
{
  "lint_score": 85,
  "lint_warnings": ["acceptance_criteria style"],
  "semantic_findings": [
    {
      "category": "vague_verb" | "implicit_assumption" | "missing_ac" | "hidden_nfr" | "mixed_concerns" | "over_specification",
      "location": "section/paragraph reference",
      "current_text": "the relevant snippet",
      "issue": "what's wrong",
      "suggested_fix": "rewritten version",
      "impact": "high" | "medium" | "low"
    }
  ]
}
```

Don't be exhaustive. 5-10 high-impact findings is far better than 50 nitpicks.
