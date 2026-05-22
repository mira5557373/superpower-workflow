# superpower-workflow — Design Spec

**Date:** 2026-05-22
**Spec version:** 1.2 (ultrathink validation)
**Status:** Approved for implementation planning
**Owner:** project author
**Runtime:** Python 3.11+

> **Reading guide.** This spec describes a reusable automation system that replaces the human loop between superpowers skill invocations. After `brainstorming` produces a spec, this system handles milestone decomposition, plan writing, implementation, review, and push — fully unattended.

---

## 1. Overview

`superpower-workflow` is a CLI tool + skills package that automates the post-brainstorming development lifecycle. It bridges the gap between the superpowers skill ecosystem (which provides `brainstorming`, `writing-plans`, `subagent-driven-development`) and unattended execution across multiple milestones.

**The problem it solves:** For large projects, the superpowers flow produces a spec, but a human must manually drive the loop: "plan M1" → "implement M1" → "review M1" → "now plan M2" → repeat. This system automates that human loop.

**The system ships as:**
- A **GitHub repository** (`superpower-workflow`), pip-installable
- **2 global skills** installed to `~/.claude/skills/`
- **1 Stop hook** for convergence enforcement
- **1 slash command** for interactive use
- A **CLI entry point** (`sw`) for orchestration

**It works with ANY project** that has a spec produced by `superpowers:brainstorming`.

### How it fits with superpowers

```
HUMAN (interactive)                    AUTOMATION (unattended)
┌─────────────────────┐               ┌──────────────────────────────────┐
│ brainstorming skill  │               │  superpower-workflow (sw)        │
│ (user + Claude)      │               │                                  │
│                      │  spec.md      │  Phase 0: Decompose → milestones │
│ Produces spec ───────┼──────────────►│  Per milestone:                  │
│                      │               │    Phase A: Plan + Ultrathink    │
│                      │               │    Phase B: Implement            │
│                      │               │    Phase C: Review + Fix         │
│                      │               │    Phase D: Push + Tag           │
│                      │               │  Loop until all milestones done  │
└─────────────────────┘               └──────────────────────────────────┘
```

---

## 2. Goals and Non-Goals

### Goals
- Fully unattended execution of the 10-step per-milestone workflow
- Reusable across any project with a superpowers spec
- Convergence-based review loops (gap-count-driven, with max_iterations as a safety cap)
- Resumable from any failure point
- Cost-controlled with per-phase and total budget caps
- Cross-platform (Windows, macOS, Linux)
- Distributable via GitHub + pip

### Non-Goals
- Replacing `superpowers:brainstorming` (design stays interactive)
- Real-time collaboration or multi-user coordination
- CI/CD integration (this is a local development tool)
- GUI or web dashboard (CLI-only in v1)
- Concurrent milestone execution (sequential in v1)

---

## 3. Architecture

### 3.1 Components

| Component | Location | Purpose |
|---|---|---|
| `sw` CLI | pip-installed entry point | User-facing commands |
| Orchestrator | `src/superpower_workflow/orchestrator.py` | Core milestone loop |
| Runner | `src/superpower_workflow/runner.py` | `claude -p` subprocess wrapper with retry |
| Decomposer | `src/superpower_workflow/decomposer.py` | Spec → milestone breakdown |
| Prompts | `src/superpower_workflow/prompts.py` | Phase-specific prompt templates |
| Context | `src/superpower_workflow/context.py` | Git-based prior-milestone context |
| State | `src/superpower_workflow/state.py` | Atomic state persistence |
| Estimator | `src/superpower_workflow/estimator.py` | Cost/duration estimates |
| Doctor | `src/superpower_workflow/doctor.py` | Pre-flight health checks |
| Logger | `src/superpower_workflow/logger.py` | Structured file logging |
| Convergence Hook | `src/superpower_workflow/hooks/convergence_gate.py` | Stop hook (exit code 2) |
| Ultrathink Skill | `skills/ultrathink-gap-analysis/SKILL.md` | ≥20-gap adversarial review |
| Post-Impl Review Skill | `skills/post-impl-review/SKILL.md` | Implementation review + fix |
| Slash Command | `commands/ultrathink.md` | Interactive `/ultrathink` |
| Install Script | `install.py` | Copy skills/hooks to `~/.claude/` |
| Templates | `templates/workflow.json` | Per-project config template |

### 3.2 Execution Model

Each phase of each milestone is a **separate `claude -p` invocation** with fresh context. This prevents context exhaustion across 30+ milestones.

```
sw run
  ├── Pre-flight checks (lockfile, clean git, green tests, budget)
  ├── Auto-decompose if no milestones in config
  ├── For each milestone:
  │   ├── Phase A: claude -p "Plan + Ultrathink"
  │   │   └── Stop hook enforces convergence loop
  │   ├── Capture plan_commit_sha (HEAD after Phase A)
  │   ├── git tag pre-impl/{milestone}         (rollback point)
  │   ├── Phase B: claude -p "Implement"
  │   ├── Phase C: claude -p "Review + Fix"
  │   │   └── Stop hook enforces convergence loop
  │   ├── Phase D: claude -p "Push + Tag"
  │   ├── Update state (atomic write)
  │   ├── Log cumulative cost
  │   └── Delay (rate limit protection)
  └── Completion summary + optional webhook notification
```

### 3.3 Convergence Mechanism

The Stop hook (`convergence_gate.py`) enforces review loops:

1. Claude runs ultrathink, writes `.claude/.gap-report.json`
2. Claude tries to stop
3. Hook reads `.workflow-phase.json` (phase state) and `.gap-report.json`
4. If not converged: **exit code 2** — stderr message fed back to Claude, Claude continues
5. If converged: **exit code 0** — Claude stops normally

**Hook NEVER runs tests.** It only reads the gap report. Testing is the skill's responsibility.

**Lifecycle:** The orchestrator creates `.workflow-phase.json` at the start of Phase A and Phase C, and deletes it at the end of each phase. The skill writes `.gap-report.json` during its analysis. Both files are transient.

**`.workflow-phase.json` schema:**
```json
{
  "phase": "ultrathink",
  "iteration": 0,
  "max_iterations": 5,
  "previous_important_gaps": null
}
```
`phase` is `"ultrathink"` (Phase A) or `"review"` (Phase C). `previous_important_gaps` is updated by the hook after each pass to enable convergence trending checks in §11.1.

**Safety:** Hook checks for `.workflow-phase.json` first. If absent (normal interactive session), exits 0 immediately. Interactive sessions are never affected.

### 3.4 The Gap Report Contract

Skills write `.claude/.gap-report.json` with this exact schema:

```json
{
  "pass": 2,
  "critical_gaps": 0,
  "architectural_gaps": 1,
  "important_gaps": 2,
  "minor_gaps": 5,
  "deferred_gaps": 3,
  "total_gaps_found": 10,
  "gaps_fixed_this_pass": 4,
  "tests_green": true,
  "lint_clean": true,
  "converged": true
}
```

**Field semantics:**
- `critical_gaps` and `important_gaps` count gaps **remaining after this pass's fixes**, not total ever found. These are the convergence signals.
- `architectural_gaps` counts 🔴-architectural gaps (needs human judgment). These are **informational only** — the hook ignores them for convergence. They are reported in status/logs.
- `tests_green` and `lint_clean` reflect the state after this pass's fixes.
- `converged` is informational (for logging/status). The hook computes convergence from gap counts + test/lint status, not from this field.
- If a verify command is `null` in `workflow.json`, the corresponding status field (`tests_green` or `lint_clean`) defaults to `true`.

---

## 4. CLI Design

### 4.1 Commands

```
sw init                              # Create .claude/workflow.json + .gitignore entries
                                     # Auto-discover spec from docs/superpowers/specs/
                                     # Optionally generate CLAUDE.md from spec conventions

sw doctor                            # Pre-flight checks:
                                     #   Claude Code version, skills installed (hash match),
                                     #   hook registered, workflow.json valid, clean git state

sw decompose                         # Two-pass decomposition:
                                     #   Pass 1: Claude reads spec → proposes milestones
                                     #   Pass 2: Claude validates milestones against spec
                                     #   Output: milestones written to workflow.json

sw estimate                          # Cost range: milestones × budget caps × 50-100%
                                     # Duration range: milestones × avg phase time

sw run                               # Full unattended execution
sw run --milestone p1-m2             # Single milestone
sw run --from p1-m3 --to p1-m8       # Range of milestones
sw run --phase p1                    # All milestones matching phase prefix
sw run --dry-run                     # Preview without executing

sw status                            # Completed milestones, current/failed milestone,
                                     #   remaining milestones, cumulative cost, ETA

sw resume                            # Smart resume from exact failure point:
                                     #   Phase A/C: restart the phase (coherent artifacts)
                                     #   Phase B: check git log for committed tasks;
                                     #     ≥50% done → advance to C, <50% → --resume session
```

### 4.2 Pre-Flight Checks (`sw run`)

1. Acquire lockfile `.claude/.workflow.lock` (abort if locked)
2. Check `git status --porcelain` (abort if uncommitted changes)
3. Run verify commands (abort if not green; skip if `verify_commands` value is `null`)
4. Check milestones exist (auto-decompose if not)
5. Validate milestone dependency ordering
6. Snapshot spec SHA for consistency during run
7. Check cumulative cost against `max_total_budget_usd`
8. Delete stale `.gap-report.json` and `.workflow-phase.json`
9. Start execution

---

## 5. Per-Project Configuration

### 5.1 `.claude/workflow.json`

```json
{
  "schema_version": 1,
  "spec": "docs/superpowers/specs/2026-05-21-e2e-agent-design.md",
  "model": "opus",
  "fallback_model": "haiku",
  "effort": {
    "plan": "max",
    "implement": "high",
    "review": "max",
    "push": "low"
  },
  "budgets": {
    "plan": 25,
    "implement": 100,
    "review": 40,
    "push": 3
  },
  "max_total_budget_usd": 500,
  "delay_between_phases_seconds": 10,
  "convergence": {
    "max_iterations": 5,
    "min_gaps_for_substantial": 20,
    "persistent_gap_downgrade_after": 3
  },
  "verify_commands": {
    "test": "python -m pytest -q",
    "lint": "python -m ruff check .",
    "format": "python -m ruff format --check ."
  },
  "git_strategy": "main",
  "notification_webhook": null,
  "milestones": [
    {
      "name": "p1-m2-knowledgestore",
      "spec_sections": "4.3, 6.1",
      "description": "SQLite-backed KnowledgeStore",
      "depends_on": ["p1-m1-foundations"],
      "budget_override": null
    }
  ]
}
```

### 5.2 Runtime State Files (gitignored)

| File | Purpose |
|---|---|
| `.claude/workflow-state.json` | Completed milestones, current index, cumulative cost |
| `.claude/.workflow-phase.json` | Current phase + iteration count (created/deleted per phase) |
| `.claude/.gap-report.json` | Last gap analysis results (created/deleted per phase) |
| `.claude/.workflow.lock` | Concurrency guard (PID-based lockfile) |
| `.claude/workflow-<run-id>.log` | Structured log per run |

All runtime files are added to `.gitignore` by `sw init`.

### 5.3 State Persistence

State writes are **atomic** (write to `.tmp`, then `os.replace()`). State tracks:

```json
{
  "current_milestone_index": 3,
  "current_step": null,              // null | "plan" | "implement" | "review" | "push"
  "last_phase_session_id": null,     // session_id from --output-format json
  "plan_commit_sha": null,           // HEAD SHA captured after Phase A
  "completed": ["p1-m1-foundations", "p1-m2-knowledgestore", "p1-m3-indexer"],
  "total_cost_usd": 127.45,
  "spec_sha": "abc123",
  "run_id": "20260522-143000",
  "started_at": "2026-05-22T14:30:00Z"
}
```

---

## 6. Skills

### 6.1 ultrathink-gap-analysis

**Type:** Technique skill (global, `~/.claude/skills/`)

**Trigger:** User says "ultrathink", invokes `/ultrathink`, or orchestrator invokes during Phase A/C.

**Procedure:**

1. **Detect mode:** `.md` target → plan review. Code target → implementation review.
2. **Read project config:** Check `.claude/workflow.json` for `verify_commands` and `convergence` settings. Use defaults if absent.
3. **Artifact size check:** >500 lines combined → dispatch independent reviewer via Agent tool. ≤500 lines → analyze directly.
4. **Read previous gap report** (if exists) to avoid re-enumerating fixed gaps.
5. **Baseline verification** (implementation mode): run project's test + lint commands.
6. **Enumerate gaps:** ≥20 for substantial artifacts (>200 lines combined). All genuine gaps for smaller artifacts. Each gap requires: reference (file:line), rationale (1 sentence), action (fix/defer/accept).
7. **Categorize:**
   - 🔴-mechanical: auto-fixable (dead code, missing test, typo)
   - 🔴-architectural: needs human judgment (flag in report, don't auto-fix in unattended mode)
   - 🟡 Important: design smell, missing coverage, edge case
   - 🟢 Acceptable: documented deferral to specific future milestone
   - 🔵 Minor: naming, style
8. **Fix** all 🔴-mechanical + 🔵 fixes. Flag 🔴-architectural.
9. **Write `.gap-report.json`** with exact schema (§3.4).
10. **Verify** (implementation mode): run test + lint. Must be green.

**Convergence criteria** (same formula as §11.1):

```
converged = (
    critical_gaps == 0 AND
    (important_gaps <= 3 OR important_gaps <= previous_pass_important * 0.5)
) OR pass >= max_iterations
```

Where `important_gaps` is the value in the current gap report and `previous_pass_important` is tracked in `.workflow-phase.json` (updated by the hook after each pass).

Persistent important gaps (same gap across 3 consecutive passes) → auto-downgrade to 🟢 Acceptable with logged warning.

### 6.2 post-impl-review

**Type:** Technique skill (global, `~/.claude/skills/`)

**Trigger:** Orchestrator invokes during Phase C, or user invokes after completing implementation.

**Scope:** Files from `git diff --name-only <plan-commit>..HEAD`, where `plan_commit_sha` is captured by the orchestrator after Phase A completes and stored in `workflow-state.json`.

**Differences from ultrathink:**
- Stricter convergence: `important_gaps == 0` (not just critical)
- Invokes `requesting-code-review` as a sub-step for quality verification
- All fixes in a single commit per pass: `fix: post-impl review fixes for {milestone}`

### 6.3 Slash Command

`/ultrathink [target]` — invoke ultrathink-gap-analysis on `$ARGUMENTS`. Default target: files changed in last commit (`git diff --name-only HEAD~1`).

---

## 7. Prompt Design

### 7.1 Prompt Structure

Each `claude -p` invocation uses TWO channels:
- `--append-system-prompt`: Critical instructions that survive context compaction
- Main prompt (`-p`): Task-specific instructions, under 500 words

**System prompt (all phases):**
```
Do NOT ask clarifying questions. Use best judgment and note uncertainties.
Follow all instructions in CLAUDE.md if present.
If your context was compacted, re-read the plan or spec before continuing.
Use conventional commits. Follow TDD when implementing code.
```

### 7.2 Phase A Prompt (Plan + Ultrathink)

```
You are executing Phase A (Plan + Ultrathink) for milestone {name}.

Context: {context_summary}

1. Read the spec at {spec_path}, focusing on sections {sections}.
2. Use the superpowers:writing-plans skill to create a TDD implementation plan
   (10-25 tasks). Save to docs/superpowers/plans/{date}-{name}.md
   ({date} = current date in YYYY-MM-DD format)
3. Run ultrathink-gap-analysis on the plan.
4. Fix critical gaps inline. Write .claude/.gap-report.json.
5. Commit the final plan.
```

### 7.3 Phase B Prompt (Implement)

```
You are executing Phase B (Implementation) for milestone {name}.

Context: {context_summary}

Execute the plan at {plan_path} using the superpowers:subagent-driven-development
skill. Implement ALL tasks with TDD (red → green → commit per task).
If a task exceeds 25 sub-tasks, report OVERSIZED.
Commit each task individually with conventional commit messages.

If context is compacted, re-read the plan at {plan_path}.
```

### 7.4 Phase C Prompt (Review + Fix)

```
You are executing Phase C (Review + Fix) for milestone {name}.

Context: {context_summary}

1. Run post-impl-review on all files changed since {plan_commit_sha}.
2. Fix ALL critical-mechanical and important issues. Flag architectural gaps in the report.
3. Commit fixes as a single commit.
4. Write .claude/.gap-report.json.

Verification: {verify_test}, {verify_lint}, {verify_format}
```

### 7.5 Phase D Prompt (Push + Tag)

```
Tag HEAD as {name}. If remote origin exists, run:
git push origin {branch} --tags
If push fails, report TAG_ONLY.
```

`{branch}` is derived from `git_strategy`: `"main"` → `main`, `"branch_per_milestone"` → `milestone/{name}`.

### 7.6 Context Generation

The `{context_summary}` placeholder is auto-generated by the orchestrator from git history:

- **Last 3 milestones:** Detailed (name + key modules created)
- **Older milestones:** One-line summary
- **Example:** "M1-M8 complete (core library + subagents). Recent: M9 (CLI: init/doctor/run/status), M10 (Skill Adapter: SKILL.md binding), M11 (RunContext: pydantic↔dataclass bridge)."

Capped at 200 words to prevent prompt bloat.

---

## 8. Error Handling

### 8.1 Error Classification

| Error | Category | Action |
|---|---|---|
| Model unavailable | Retryable | Retry with `fallback_model` |
| Network failure | Retryable | 3 retries, exponential backoff (10s/30s/90s) |
| Phase timeout (2h) | Conditional | Check git log for progress; resume or retry |
| Tests fail after max review iterations | Fatal | Stop, log error with gap report contents |
| Budget exceeded (Phase A) | Fatal | Halt milestone (can't implement without a plan) |
| Budget exceeded (Phase B) | Conditional | Advance to Phase C (review partial work) |
| Budget exceeded (Phase C) | Non-fatal | Log warning, advance to Phase D (push what exists) |
| Total budget exceeded | Fatal | Stop run entirely |
| Oversized plan (>25 tasks) | Fatal (milestone) | Skip to next milestone; log: "Plan exceeded 25 tasks — consider splitting" |
| Malformed gap report | Retryable | Hook sends "rewrite gap report" via exit 2 |
| Git push fails | Non-fatal | Tag locally, log warning, continue |

### 8.2 Phase B Timeout Recovery

If Phase B times out with partial progress:
- Check `git log` for committed tasks since `pre-impl/{milestone}` tag
- If ≥50% tasks completed: advance to Phase C (review partial implementation)
- If <50% tasks completed: retry Phase B with `claude -p --resume {session_id}` (session ID captured from Phase B's JSON output)

### 8.3 Rollback

Before Phase B, the orchestrator creates `git tag pre-impl/{milestone}`. If Phase C exhausts retries:

```
FATAL: Milestone {name} failed after {n} review iterations.
  2 critical gaps remaining.
  Rollback: git reset --hard pre-impl/{name}
  Then: sw resume
```

---

## 9. Decomposition

### 9.1 Process

`sw decompose` runs two `claude -p` calls:

**Pass 1 — Propose** (uses `--json-schema` to enforce structured output):
```
Read the spec at {spec_path}. Identify implementation milestones.
Rules:
- Each milestone: 10-25 tasks of TDD work (1-3 days)
- Group by dependency (foundations first)
- Each milestone independently testable
- Name format: {phase}-m{N}-{short-name}
Output as JSON array of milestones, each with: name, spec_sections, description, depends_on.
```

**Pass 2 — Validate:**
```
Review these proposed milestones against the spec.
Check: all spec sections covered? Dependencies correct? Sizes reasonable?
Fix any issues. Output corrected milestone list.
```

### 9.2 Small Projects

If the spec is <200 lines and describes a single feature, the decomposer creates a single milestone covering everything. No multi-milestone overhead.

---

## 10. Installation & Distribution

### 10.1 Repository Structure

```
superpower-workflow/
├── pyproject.toml                    # pip installable; entry point: sw = superpower_workflow.cli:main
├── README.md
├── LICENSE (MIT)
├── src/superpower_workflow/
│   ├── __init__.py                   # __version__
│   ├── cli.py                        # argparse entry point
│   ├── orchestrator.py               # Core milestone loop
│   ├── decomposer.py                 # Spec → milestones
│   ├── estimator.py                  # Cost/duration
│   ├── state.py                      # Atomic state management
│   ├── runner.py                     # claude -p wrapper + retry
│   ├── logger.py                     # Structured file logging
│   ├── prompts.py                    # Prompt templates
│   ├── context.py                    # Git-based context generation
│   ├── doctor.py                     # Health checks
│   └── hooks/
│       └── convergence_gate.py       # Stop hook (importable)
├── skills/
│   ├── ultrathink-gap-analysis/SKILL.md
│   └── post-impl-review/SKILL.md
├── commands/ultrathink.md
├── templates/workflow.json
├── install.py                        # Robust: mkdir, hash-check, overwrite/skip
└── tests/
    ├── test_state.py
    ├── test_estimator.py
    ├── test_prompts.py
    ├── test_convergence_gate.py
    ├── test_runner.py                # Mock subprocess
    ├── test_decomposer.py            # Mock Claude response
    ├── test_cli.py
    └── test_orchestrator.py          # Full flow mock
```

### 10.2 Installation

```bash
git clone https://github.com/<user>/superpower-workflow.git
cd superpower-workflow
pip install -e .                     # Installs sw command
python install.py                    # Copies skills/hooks/commands to ~/.claude/
```

### 10.3 Per-Project Setup

```bash
cd /path/to/my-project
sw init                              # Creates .claude/workflow.json
sw decompose                         # Claude proposes milestones
sw estimate                          # Review cost before committing
sw run                               # Execute unattended
```

### 10.4 Install Script Behavior

- Creates `~/.claude/skills/`, `~/.claude/hooks/`, `~/.claude/commands/` if missing
- Compares file hashes before copying (skip identical, prompt for modified)
- Registers Stop hook in `~/.claude/settings.json` (reads existing, merges, writes)
- Reports installed versions

---

## 11. Convergence Criteria

### 11.1 Plan Ultrathink (Phase A)

```
converged = (
    critical_gaps == 0 AND
    (important_gaps <= 3 OR important_gaps <= previous_pass_important * 0.5)
) OR pass >= max_iterations (default 5)
```

`important_gaps` refers to the value in the current pass's gap report (remaining after fixes). `previous_pass_important` is read from `.workflow-phase.json` (updated by the hook after each pass). On the first pass (no prior data), `previous_pass_important` is treated as infinity — only the `important_gaps <= 3` condition applies.

### 11.2 Implementation Review (Phase C)

```
converged = (
    critical_gaps == 0 AND
    important_gaps == 0 AND
    tests_green == true AND lint_clean == true
) OR pass >= max_iterations (default 5)
```

`tests_green` and `lint_clean` are read from the gap report, where the skill records them after running verify commands.

### 11.3 Persistent Gap Auto-Downgrade

If the same important gap appears in 3 consecutive passes without resolution (matched by file reference + gap category), auto-downgrade to 🟢 Acceptable. Log a warning. This prevents infinite loops from subjective design concerns.

---

## 12. Logging & Monitoring

### 12.1 Structured Log

Each run creates `.claude/workflow-<run-id>.log`:

```
[2026-05-22T14:30:00Z] RUN_START run_id=20260522-143000 milestones=13 spec_sha=abc123
[2026-05-22T14:30:05Z] MILESTONE_START name=p1-m2-knowledgestore
[2026-05-22T14:30:06Z] PHASE_A_START
[2026-05-22T14:45:23Z] PHASE_A_COMPLETE cost=4.20 duration=920s converged=true passes=2
[2026-05-22T14:45:33Z] PHASE_B_START
[2026-05-22T16:12:45Z] PHASE_B_COMPLETE cost=18.50 duration=5232s tasks=15
[2026-05-22T16:12:55Z] PHASE_C_START
[2026-05-22T16:42:10Z] PHASE_C_COMPLETE cost=6.30 duration=1755s converged=true passes=1
[2026-05-22T16:42:15Z] PHASE_D_COMPLETE cost=0.18 tag=p1-m2-knowledgestore pushed=true
[2026-05-22T16:42:15Z] MILESTONE_COMPLETE name=p1-m2-knowledgestore total_cost=29.18
```

Full Claude output NOT captured in log (too large). Use `sw run --verbose-log` for debugging.

### 12.2 Completion Notification

On run completion or fatal failure, the orchestrator:
1. Writes `.claude/workflow-complete.json` with summary
2. Prints terminal bell character (`\a`)
3. If `notification_webhook` is set: POST `{status, milestone, cost, duration}` (no code content)

---

## 13. Cost Estimates

### 13.1 Per-Milestone Estimate

| Phase | Optimistic | Pessimistic |
|---|---|---|
| A (Plan + Ultrathink) | $3, 20min | $8, 45min |
| B (Implementation) | $10, 1hr | $30, 3hr |
| C (Review + Fix) | $4, 30min | $12, 1hr |
| D (Push) | $0.20, 2min | $0.20, 2min |
| **Total/milestone** | **~$17** | **~$50** |

### 13.2 Budget Protection

- Per-phase cap via `--max-budget-usd` on each `claude -p` call
- Per-project cap via `max_total_budget_usd` in workflow.json
- Orchestrator checks cumulative cost after each phase
- `sw estimate` previews total before running

---

## 14. Future Work (v2)

- Concurrent milestone execution (independent milestones in parallel)
- Web dashboard for monitoring
- Slack/Discord notification integrations
- `sw uninstall` command
- Claude Code version pinning
- Coverage report generation
- Agent Teams integration for Phase B parallelism
- Multi-spec project support (`sw run --config <path>`)

---

## 15. Appendix

### 15.1 Design Validation

This spec was validated through 4 ultrathink passes during brainstorming:
- **Pass 1:** 14 gaps (CLI design)
- **Pass 2:** 24 gaps (skills, hook, config)
- **Pass 3:** 25 gaps (operations, reliability, edge cases)
- **Pass 4:** 20 gaps (prompts, recovery, runtime)
- **Total: 93 gaps** — all critical and important resolved in design
- **Spec self-review (v1.1):** 16 issues found (contradictions, ambiguities, missing field semantics, cross-platform issues, cross-section inconsistencies). All fixed inline.
- **Ultrathink validation (v1.2):** 15 additional issues found (tag name inconsistency in §8.2, missing .workflow-phase.json schema, Phase A convergence data flow gap, prompt/skill contradiction on architectural gaps, oversized plan not treated as fatal, undefined first-pass convergence, missing current_step values, missing entry point spec). All fixed inline.
