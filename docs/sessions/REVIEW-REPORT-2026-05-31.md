# Overnight Review — v1.1.8/v1.1.9/v1.2.0/v1.3.0 (2026-05-31)

## Executive summary

Eight HIGH findings confirmed (3 votes / 3 votes, refuted_count=0) across the four releases, plus 12 completeness gaps the lens reviewers missed. v1.1.8 carries the heaviest concentration of safety issues (path traversal in `sw clean`, PID-reuse in `sw server stop`, four non-atomic-write violations of the project's stated convention). v1.3.0 ships two pieces of unwired dead code (statusline.py with no CLI/hook registration; four new auto-skills that the orchestrator never invokes) plus a broken config-key reference in `code-quality-loop/SKILL.md` (`validation.qa_strict_iteration_budget` does not exist). Soak was NOT run — none of the confirmed HIGHs sit on the orchestrator hot path (`_run_milestone` / `_run_spec_compliance` / `_run_feature_verification` / `_run_strict_mode_loop` are unchanged), and the TrustButVerifyPipeline is forward-compat scaffolding not yet wired. Top recommendation: ship a v1.1.8.2/v1.3.1 patch that (a) closes the two safety HIGHs in `cli.py:954` and `cli.py:1217`, (b) wires `_install_project_local` + gitignore + ProjectRegistry into `_cmd_onboard`, (c) routes `_emit_spec_lint_event` through `TelemetryEmitter`, and (d) fixes the `code-quality-loop` SKILL.md config key — these are all localized, no orchestrator changes.

## Confirmed HIGH/CRITICAL findings

| file | line | release | lens | severity | description | suggested_fix |
|---|---|---|---|---|---|---|
| `scripts/complexity_audit.py` | 29 | v1.2.0 | correctness | HIGH | `_max_nesting` counts each `elif` as a nested `If` because Python's AST models `elif` as a nested `If` in `orelse`. A flat `if/elif/elif/elif/else` reports nesting=4 instead of 1. CI uses `--max-nesting 7`, so this can fail CI on flat code and pass deeply-nested `match-case` code. Reproduced live: 4-arm elif chain → `_max_nesting(fn) == 4`. | When recursing into `If.orelse` where the sole element is another `If` (elif), do not increment depth. Walk if-chains iteratively as a single level. |
| `tests/test_recommender.py` | 93 | v1.1.9 | test rigor | HIGH | `assert report.recommended in ("sonnet", "opus")` accepts both possible answers, so the test cannot fail. This is the only test exercising `efficiency = quality_score / cost` in `recommend()`; with the assertion neutered, the recommendation algorithm is effectively untested. Second clause `"milestone" in report.rationale` is a tautology because the production rationale always contains "milestone(s)" (recommender.py:171-174). | Compute the expected winner deterministically from the documented weights; assert `report.recommended == "sonnet"`. Replace the OR with a non-tautological rationale check (e.g., `best.model in report.rationale`). |
| `src/superpower_workflow/cli.py` | 994 | v1.1.7 (carried into v1.1.8/v1.1.9) | integration | HIGH | `_emit_spec_lint_event` writes directly to `.claude/telemetry.jsonl` (raw `f.write(json.dumps(event)+"\n")`) bypassing `TelemetryEmitter`/`TelemetryDbWriter`. When the unified server runs, the writer never sees the event so it never reaches Postgres in real time. Hardcoded path also ignores `config.telemetry.path` (cf. `_cmd_metrics:680`, `_cmd_clean:950-951`). | Construct a `SpecLintCompleted` dataclass (already exists at telemetry.py:279) and emit through a `TelemetryEmitter` bound to the resolved telemetry path. Extract a `_resolve_telemetry_path(project_root)` helper. |
| `src/superpower_workflow/db/sync_adapter.py` | 79 | v1.1.7 | integration | HIGH | `sw server sync` silently drops events with `run_id=""` (lines 79-84: `if run_id not in run_uuids: ... continue`). `sw lint-spec` standalone emits with `run_id=""` (cli.py:999), so standalone lint events are NEVER persisted to the DB, only to JSONL. | Add a project-scoped event ingestion path: when `run_id` is empty and `event_type` is in a project-level set (e.g., `{"spec_lint_completed"}`), insert into `SwEvent` with `run_id=NULL` (requires schema relax) or attach to a synthetic standalone run per project. |
| `src/superpower_workflow/pipelines/trust_but_verify.py` | 54 | v1.2.0 | integration | HIGH | Callable signatures do NOT match the orchestrator: `spec_compliance_fn: Callable[[Any], tuple[dict|None, float]]` takes 1 arg but `_run_spec_compliance(self, name, ms)` takes 2; `feature_verification_fn` takes 1 vs orchestrator's `_run_feature_verification(self, name)`; `strict_loop_fn` expects `(ctx, compliance, verification) -> (list[dict], float)` but `_run_strict_mode_loop` takes 7 args and returns only `float` — no iterations list (orchestrator.py:1948 returns `total_cost` only; iterations are emitted via `self._telemetry.emit(StrictModeIteration(...))` at orchestrator.py:1934). When v1.2.1 wires this, every stage will need a non-trivial adapter, and the test suite's lambdas don't exercise real signatures — false confidence. | Update `TrustButVerifyPipeline` callable signatures to match the orchestrator (accept a `ctx` exposing name+ms+model+fallback+logger), and have the strict loop also return iterations; or document the adapter pattern and add an integration test that wraps the actual orchestrator methods into pipeline-compatible callables. |
| `src/superpower_workflow/cli.py` | 606 | v1.1.9 | integration | HIGH | `_cmd_onboard` is NOT feature-parity with `_cmd_init`: skips (1) gitignore population (SW_GITIGNORE_ENTRIES + PYTHON_GITIGNORE_ENTRIES at cli.py:394-409), (2) `_install_project_local(claude_dir)` (cli.py:412) which installs bundled skills/commands/settings.local.json/Stop hook, (3) ProjectRegistry registration (cli.py:415-420). Onboarded projects have no convergence_gate Stop hook, no superpowers plugin, no skills, no gitignore safety. | Extract gitignore-append + `_install_project_local` + registry-register block into `_postinit_setup(project_root)` and call from both `_cmd_init` and `_cmd_onboard`. |
| `src/superpower_workflow/cli.py` | 954 | v1.1.8 | safety | HIGH | Path traversal in `sw clean`: telemetry path read from workflow.json with no sanitization, then `unlink()`-ed. A workflow.json with `"telemetry": {"path": "../../etc/passwd"}` makes `sw clean` a file-deletion primitive against arbitrary paths the user can read. No `.resolve().is_relative_to(project_root)` check. | `telemetry_path = (project_root / rel).resolve()` then assert `telemetry_path.is_relative_to(project_root.resolve())` before `.unlink()`. Reject (warn + skip) otherwise. |
| `src/superpower_workflow/cli.py` | 1217 | v1.1.8 | safety | HIGH | `sw server stop` reads PID from `~/.claude/sw-server.pid` and `os.kill(pid, SIGTERM)` with no verification the PID still belongs to the sw server. On long-running systems PIDs are reused; a stale PID file from a prior boot can SIGTERM an unrelated process. | Before SIGTERM, validate `psutil.Process(pid).cmdline()` matches `sw server start` or contains `superpower_workflow.server`. At minimum `os.kill(pid, 0)` + compare PID-file mtime against `/proc/<pid>/stat` start time. Refuse to kill on mismatch and prompt. |

## Refuted findings

None. All eight findings were 3/3 confirmed (refuted_count=0) across reviewer votes.

## Medium/Low findings

(Not adversarially verified; surfaced by lens reviewers — listed for completeness.)

Correctness:
- `onboard.py:137` (MEDIUM, v1.1.9) — Spec selection accepts out-of-range/zero/negative indices silently (Python negative indexing does not raise IndexError).
- `recommender.py:159` (MEDIUM, v1.1.9) — "only one model has >=3 milestones" rationale is the opposite of the real condition (no model has >=3).
- `recommender.py:94` (MEDIUM, v1.1.9) — `spec_compliance_rate` can exceed 1.0 when multiple `spec_compliance_completed` events fire per milestone (strict-mode reruns).
- `complexity_audit.py:40` (MEDIUM, v1.2.0) — Both `_cyclomatic_complexity` and `_max_nesting` recurse into nested FunctionDef bodies; parent function double-counts inner-function branches.
- `complexity_audit.py:40` (LOW, v1.2.0) — CC misses `ast.Match`/`ast.match_case`, comprehension `if`s, assert. Match-case code is silently under-counted.
- `statusline.py:47` (LOW, v1.3.0) — `current_milestone_index` can exceed `total`, rendering `M11/10`.
- `statusline.py:21` (LOW, v1.3.0) — `DEFAULT_STATUSLINE_PATH` constant defined but never used; `write_statusline_file` hardcodes `statusline.txt`.
- `cli.py:396` (LOW, v1.1.8) — Gitignore dedupe uses substring match; a comment containing a candidate as substring suppresses real insertion.
- `project_detect.py:76` (LOW, v1.1.8) — `_QUALITY_GATES` contains explicit `None` values copied verbatim into workflow.json.

Test rigor:
- `tests/test_recommender.py:94` (MEDIUM, v1.1.9) — Tautology in rationale assertion (separately listed as HIGH above; same line, second clause).
- `tests/test_project_detect.py:87` (MEDIUM, v1.1.8) — `test_mixed_python_typescript_merges_dep_scans` does not exercise merge codepath; passes even if `for secondary in langs[1:]` loop is deleted.
- `tests/test_onboard.py:101` (MEDIUM, v1.1.9) — `test_interactive_with_canned_stdin_writes_config` never calls `write_config`; misleading name.
- `tests/test_onboard.py:93` (LOW, v1.1.9) — `test_writes_atomically` does not verify `.tmp + os.replace` pattern; would pass with naive `write_text`.
- `tests/test_trust_but_verify_pipeline.py:26` (LOW, v1.2.0) — `test_compliance_only` doesn't pin `result.converged` or `result.verification_report is None`.
- `tests/test_trust_but_verify_pipeline.py` (MEDIUM, v1.2.0, module-level) — Missing edge cases: strict_mode=True with strict_loop_fn=None; stage callable raising; `feature_verification_fn` returning None for report; `cost=None`.
- `tests/test_complexity_audit.py:58` (LOW, v1.2.0) — Hardcodes `_run_milestone` as expected violator; brittle to v1.2.1 refactor.
- `tests/test_statusline.py:22` (LOW, v1.3.0) — Missing edge cases: out-of-range `current_milestone_index`, negative/NaN cost, OSError on read, missing config milestones, `current_step=None`.
- `tests/test_init_quality_gates.py:32` (LOW, v1.1.8) — No test for `minimal=True` + `with_quality_gates=True` interaction.

Integration:
- `src/superpower_workflow/db/writer.py:197` (MEDIUM, v1.1.7) — Writer drops `spec_lint_completed` when `run_uuid` is None; no project-scoped event table.
- `src/superpower_workflow/statusline.py:32` (MEDIUM, v1.3.0) — No `schema_version` check; future schema bump silently shows stale data.
- `src/superpower_workflow/statusline.py:1` (MEDIUM, v1.3.0) — Module ships but is not wired into any CLI subcommand/hook/`settings.local.json`. Inert library.
- `src/superpower_workflow/onboard.py:119` (MEDIUM, v1.1.9) — Wizard offers `abort`/`replace`/`merge`; only `abort` is honored. `merge` silently overwrites identically to `replace` (data-loss footgun).
- `src/superpower_workflow/cli.py:648` (LOW, v1.1.9) — `_cmd_recommend_model` hardcodes telemetry path; ignores `config.telemetry.path`.
- `src/superpower_workflow/cli.py:412` (LOW, v1.3.0) — `_install_project_local` runs even under `--minimal`, applying `defaultMode=bypassPermissions` security default to users opting for minimal.
- `src/superpower_workflow/cli.py:989` (LOW, v1.1.7) — `_emit_spec_lint_event` writes regardless of `config.telemetry.enabled`; violates user opt-out.
- `.github/workflows/test.yml:74` (LOW, v1.3.0) — Wheel-content check uses substring `in` matching; would pass if individual new skills/commands are missing.

Safety:
- `cli.py:419` (MEDIUM, v1.1.8) — Bare `except Exception: pass` after ProjectRegistry registration; silent failure.
- `cli.py:398` (MEDIUM, v1.1.8) — Non-atomic `.gitignore` append (violates CLAUDE.md `_atomic_write` convention).
- `cli.py:520` (MEDIUM, v1.1.8) — Non-atomic `.gitignore` write in `_cmd_migrate_gitignore` (can truncate-and-lose).
- `cli.py:383` (MEDIUM, v1.1.8) — Non-atomic `workflow.json` write in `_cmd_init`; two non-atomic writes back-to-back.
- `cli.py:950` (MEDIUM, v1.1.8) — Missing `schema_version` check across `_cmd_clean`, `_cmd_metrics`, `_cmd_dashboard`, `_cmd_watch`, `_cmd_audit_verify_sig`, `_cmd_server_start`, `_cmd_server_sync`.
- `cli.py:1113` (MEDIUM, v1.1.8) — `subprocess.run(['pip', ...])` uses PATH lookup instead of `[sys.executable, '-m', 'pip', ...]`.
- `cli.py:1019` (LOW, v1.1.8) — `_cmd_lint_spec` accepts absolute paths and `..` traversal via `(project_root / spec_path).resolve()` with no containment check.
- `cli.py:1183` (LOW, v1.1.8) — `contextlib.suppress(json.JSONDecodeError, OSError)` silently runs server with default config.
- `project_detect.py:116` (LOW, v1.1.8) — Marker existence check follows symlinks.
- `onboard.py:139` (LOW, v1.1.9) — Out-of-range numeric input silently coerced to literal path.
- `onboard.py:100` (LOW, v1.1.9) — `merge` choice has no implementation; identical to `replace`.
- `recommender.py:63` (LOW, v1.1.9) — `_read_telemetry` returns `[]` on any OSError; permission-denied looks identical to "no data".
- `scripts/complexity_audit.py:79` (LOW, v1.2.0) — `path.relative_to(PACKAGE_DIR.parent.parent)` raises ValueError on non-checkout layouts.
- `statusline.py:65` (LOW, v1.3.0) — Non-atomic `write_text` of statusline.txt; reader can see zero-byte/partial file.
- `statusline.py:36` (LOW, v1.3.0) — No `schema_version` check.

Documentation accuracy:
- `project_detect.py:42` (MEDIUM, v1.1.8) — CHANGELOG advertises Java/Ruby detection but no `_VERIFY_COMMANDS` or `_QUALITY_GATES` entries; empty profiles.
- `CHANGELOG.md:100` (LOW, v1.1.8) — Test-count breakdown says `+22 project_detect` but actual is `+16 project_detect + +6 init quality-gates`.
- `CHANGELOG.md:96` (MEDIUM, v1.1.8) — v1.1.8.1 deferral has no scaffolds, TODOs, or tracking issue.
- `recommender.py:155` (LOW, v1.1.9) — CHANGELOG says "fewer than 3 milestones per model"; code triggers only when NO model has >=3.
- `recommender.py:129` (LOW, v1.1.9) — `first_pass_rate = 1 - strict_iter_rate` collapses two formula terms into 0.5 weight on strict-mode penalty.
- `CHANGELOG.md:73` (MEDIUM, v1.1.9) — v1.1.9.1 deferral has no scaffolds.
- `src/superpower_workflow/__init__.py` (LOW, v1.1.9) — Top-level package re-exports nothing; advertised public symbols are not surfaced.
- `CHANGELOG.md:58` (LOW, v1.2.0) — "Functions audited: 414" but actual baseline reports 416.
- `pipelines/trust_but_verify.py:12` (LOW, v1.2.0) — Tests pin only aggregator skeleton; "behavior contract" claim is overstated.
- `_assets/skills/code-quality-loop/SKILL.md:31` (MEDIUM, v1.3.0) — References `validation.qa_strict_iteration_budget` which does not exist (real key: `validation.strict_iteration_budget`, default 8.0 not $5). See completeness HIGH below.
- `CHANGELOG.md:12` (MEDIUM, v1.3.0) — Describes code-quality-loop as orchestrator-invoked; it is a markdown asset with no Python integration.
- `statusline.py:65` (MEDIUM, v1.3.0) — `write_statusline_file` is never called from anywhere; `.claude/statusline.txt` will not be populated during a run.
- `CHANGELOG.md:27` (MEDIUM, v1.3.0) — Four v1.3.1 deferrals have no scaffolds (MCP server, native statusline API, memory integration, cost/quality hooks).
- `.github/workflows/test.yml:74` (MEDIUM, v1.3.0) — Wheel-asset-check is coarser than CHANGELOG claim "verified to ship in the wheel".

## CLI validation results

| feature | result | observed vs expected | deviations |
|---|---|---|---|
| `sw lint-spec` end-to-end (BAD/GOOD/WARN+`--strict`) | PASSED | Scenario 1 (BAD): exit 1, score 55/100, 3 FAIL incl. `no_placeholders` + `code_blocks_balanced`. Scenario 2 (GOOD): exit 0, 100/100. Scenario 3 (WARN, default): exit 0; with `--strict`: exit 1. All exit codes match expected. | BAD spec also FAILs `requirements_countable` (consistent with content). Cosmetic mojibake `�` in `quality_gates_declared` WARN hint on Windows shell (em-dash encoding). |
| `sw onboard --non-interactive` | FAILED | In an empty directory, CLI prints "Aborted. No changes written." and does NOT create `.claude/workflow.json`. `OnboardConfig.accept_existing` defaults to `"abort"`; `run_onboard(interactive=False)` returns at onboard.py:104 BEFORE the existing-file detection at onboard.py:114. `_cmd_onboard` (cli.py:606-641) then treats the default `"abort"` as user-requested abort. Validation flags themselves ARE correct when functions are called programmatically (gap_curator=True, spec_linter=True, strict_mode=False); Python project detection ALSO correct (verify_commands populated with ruff/pytest). | Smoke-test mode is non-functional via the CLI. Idempotency on rerun "works" only as a side effect of the same default-abort bug. Audit block records `accept_existing='abort'` on programmatic write — misleading. `spec_path` defaults to empty string when no `spec*.md` is detected and interactive=False; downstream `sw lint-spec`/`sw decompose` will fail. |
| `sw recommend-model` (text + JSON, with telemetry + empty path) | PASSED | With soaked telemetry: text mode prints `Recommended model: opus` and rationale; JSON emits `{models:[{model:'opus', milestone_count:1, ...}], recommended:'opus', rationale:...}`. With absent or zero-byte telemetry: text prints "No model data — run at least one milestone first."; JSON emits `{models:[], recommended:'', rationale:...}`. Exit 0 in all cases. | Em-dash renders as `?` in text mode on Windows console code page (JSON correctly UTF-8 encodes). Command reads `.claude/telemetry.jsonl` relative to cwd; no path flag. |
| `scripts/complexity_audit.py` (baseline + pass + fail thresholds) | PASSED | Baseline: "Functions audited: 416", Top-10 lists `_run_milestone` at orchestrator.py:745 with lines=502, cc=36, nest=2. Pass thresholds (`--max-lines 510 --max-cc 50 --max-nesting 7`): exit 0, "Complexity audit OK (416 functions audited)". Fail thresholds (`--max-lines 100 --max-cc 15 --max-nesting 4`): exit 1, 25 violations, `_run_milestone` mentioned. | None. |
| Statusline rendering (running / empty / corrupt) | PASSED | Scenario 1 (running): `[sw] M2/3 $5.67/$50 implement (1 done)` — exact match. Scenario 2 (empty dir): `[sw] idle` — exact match. Scenario 3 (corrupt state JSON): `[sw] idle` — exact match (JSONDecodeError caught). | None. |

## Completeness critique

Lens reviewers missed 12 gaps surfaced by the completeness audit:

HIGH:
- v1.3.0 code-quality-loop skill (`_assets/skills/code-quality-loop/SKILL.md:31`) — references `validation.qa_strict_iteration_budget` which does not exist; real key is `validation.strict_iteration_budget` (cli.py:364, onboard.py:213, read at orchestrator.py:1908) and real default is 8.0, not $5. Any agent honoring the cap reads `undefined` and never stops. No lens reviewer opened the new skill files.
- v1.3.0 statusline (`statusline.py:11`) — module self-documents as a SKELETON requiring API verification. Zero references to `statusLine` or `statusline` in cli.py/`_install_project_local`/settings templates. T3.0.4 is dead code from the user's perspective. Render works in isolation; no end-to-end visibility.
- v1.1.9 onboard/init parity, fourth divergence — `build_workflow_config` (onboard.py:219) writes `convergence: {max_iterations: 5}` only; `_cmd_init` (cli.py:252-256) writes `{max_iterations, min_gaps_for_substantial, persistent_gap_downgrade_after}`. Onboard-created projects silently use orchestrator hardcoded fallbacks for gap-downgrade logic.

MEDIUM:
- CI wheel-asset verifier (`.github/workflows/test.yml:74`) — substring `_assets/skills/` match; would pass even if all four new v1.3.0 skills are missing.
- Recommender quality_score formula collapse (`recommender.py:123-135`) — `first_pass_rate = 1 - strict_iter_rate`; documented 0.3/0.2 split becomes 0.5 weight on a single dimension. Two-model unit tests differing only in `strict_iter_rate` should show delta=0.3 per docs, but show 0.5.
- complexity_audit AST coverage (`scripts/complexity_audit.py:40,29`) — missing `ast.Match`/`ast.AsyncFor`/`ast.AsyncWith`/`ast.ExceptHandler` for nesting; missing `ast.IfExp`/`ast.Match`/`ast.match_case` for cc. Modern Python is silently under-counted.
- doctor.py not extended for v1.3.0 assets — partial install of new skills/commands undetected on the user's machine.
- v1.1.7→v1.1.8 default flips — no upgrade-path safeguard; users upgrading from v1.1.6 with `gap_curator: false` keep curator OFF silently, paying 33% more per soak.
- Orchestrator/TrustButVerifyPipeline drift not policed — no integration test wraps actual orchestrator methods; a `_run_spec_compliance` rename or return-tuple change would silently break the pipeline class.
- v1.1.8 quality_gates execution path untested end-to-end — no test exercises the runtime path from gate-execution → `.quality-gate-results.json` → convergence_gate hook → skill activation.

LOW:
- v1.3.0 sw-status command (`_assets/commands/sw-status.md`) — implicit cwd/PATH assumptions; no guidance on running from project root or using `python -m superpower_workflow` fallback.
- v1.1.9 onboard non-interactive (`onboard.py`) — `spec_path` defaults to empty string when no `spec*.md` is found; downstream commands raise unhelpful FileNotFoundError.

By area:
- Skill correctness (1 HIGH, 1 LOW): the new skill markdown files were not reviewed against actual config keys/CLI behavior.
- Wiring/integration (1 HIGH, 2 MEDIUM): statusline + auto-skills + orchestrator pipeline are not wired into runtime/install paths.
- Parity (1 HIGH): init↔onboard divergence has more touch-points than originally flagged.
- CI hardening (1 MEDIUM): wheel-asset checks too loose; doctor extension absent.
- Formula correctness (1 MEDIUM): recommender double-counts a signal; static lens missed it because the test was tautological.
- AST coverage (1 MEDIUM): complexity audit under-counts modern Python constructs.
- Upgrade safety (1 MEDIUM): no migration path for flipped defaults.

## Soak result

Not run — reason: no HIGH finding, failed validation, or completeness gap names an orchestrator hot-path regression. The orchestrator's hot-path methods (`_run_milestone`, `_run_spec_compliance`, `_run_feature_verification`, `_run_strict_mode_loop`) were not modified in any flagged HIGH. The `TrustButVerifyPipeline` signature drift is dead code (`pipelines/__init__.py` confirms "orchestrator continues to call its existing methods" and the class is not wired into `orchestrator.py:_run_milestone`). The remaining HIGHs are CLI subcommands (`_cmd_clean`, `_cmd_server_stop`, `_cmd_onboard`), telemetry plumbing (`_emit_spec_lint_event`, `DbSyncAdapter`), CI tooling (complexity_audit elif), and a test-rigor tautology. The failed onboard validation is a setup-time bug, independently fixable and verifiable without a live soak. A $15 soak would not surface anything the existing static + unit tests have not already characterized. Re-evaluate soak only if (a) any fix touches `orchestrator.py` or (b) v1.2.1 wires `TrustButVerifyPipeline` into the hot path.

## Concrete fix list

HIGH (ship in next patch):
1. HIGH → `src/superpower_workflow/cli.py:954` — Resolve telemetry_path and assert `is_relative_to(project_root.resolve())` before `unlink()`.
2. HIGH → `src/superpower_workflow/cli.py:1217` — Verify PID via `psutil.Process(pid).cmdline()` or `os.kill(pid, 0)` + PID-file mtime check before SIGTERM.
3. HIGH → `src/superpower_workflow/cli.py:606` — Extract `_postinit_setup(project_root)` (gitignore + `_install_project_local` + ProjectRegistry register) and call from both `_cmd_init` and `_cmd_onboard`; add missing `convergence.min_gaps_for_substantial` and `convergence.persistent_gap_downgrade_after` to `build_workflow_config`; add parity test asserting `sorted(_cmd_init default_config[block].keys()) == sorted(build_workflow_config(...)[block].keys())` for every nested block.
4. HIGH → `src/superpower_workflow/cli.py:994` — Construct a `SpecLintCompleted` dataclass and emit through a `TelemetryEmitter` bound to a resolved telemetry path; extract `_resolve_telemetry_path(project_root)` helper used by `_cmd_metrics`, `_cmd_clean`, `_cmd_server_sync`, `_cmd_recommend_model`, and `_emit_spec_lint_event`.
5. HIGH → `src/superpower_workflow/db/sync_adapter.py:79` — Add project-scoped ingestion path for `run_id=""` events in known project-level set (`{"spec_lint_completed"}`); insert with `run_id=NULL` or attach to a synthetic standalone run.
6. HIGH → `scripts/complexity_audit.py:29` — When recursing into `If.orelse` where the sole element is another `If`, do not increment depth (walk if-chains iteratively).
7. HIGH → `tests/test_recommender.py:93` — Replace `assert report.recommended in ("sonnet", "opus")` with `assert report.recommended == "sonnet"` (deterministic from documented weights); replace second clause with `best.model in report.rationale`.
8. HIGH → `src/superpower_workflow/pipelines/trust_but_verify.py:54` — Update callable signatures to match orchestrator (accept ctx exposing name+ms+model+fallback+logger); have `_run_strict_mode_loop` also return iterations list; add integration test wrapping actual orchestrator methods as pipeline-compatible adapters.
9. HIGH (completeness) → `src/superpower_workflow/_assets/skills/code-quality-loop/SKILL.md:31` — Replace `validation.qa_strict_iteration_budget (default $5)` with `validation.strict_iteration_budget (default $8.0)`; add a test that grep-asserts every `validation.<key>` string in any SKILL.md resolves to a real key in `cli.py` default_config and `onboard.py` `build_workflow_config`.
10. HIGH (completeness) → `src/superpower_workflow/statusline.py:1` — Either (a) wire `write_statusline_file` into orchestrator phase-transition hooks AND add a `"statusLine": {...}` entry to `_install_project_local`'s settings dict, or (b) mark module `__experimental__` and drop from public docs until v1.3.1.

MEDIUM (next milestone):
11. MEDIUM → `.github/workflows/test.yml:74` — Replace prefix list with full required set (each new skill + command path) and use exact match.
12. MEDIUM → `src/superpower_workflow/recommender.py:123-135` — Redefine `first_pass_rate` as a distinct signal (per-milestone bool: completed without any strict-mode iteration) OR reduce documented weights to reflect reality (0.4/0.5/0.1) and add unit test pinning the delta.
13. MEDIUM → `scripts/complexity_audit.py:40` — Extend `_max_nesting` isinstance tuple to include `ast.Match | ast.AsyncFor | ast.AsyncWith | ast.ExceptHandler`; extend `_cyclomatic_complexity` to include `ast.IfExp | ast.Match | ast.match_case`; add per-construct unit tests; skip recursion into nested `FunctionDef`/`AsyncFunctionDef`.
14. MEDIUM → `src/superpower_workflow/doctor.py` — Enumerate expected skill names + command files from `_assets_root()` and assert each exists under `(project_root / ".claude" / "skills")` and `(project_root / ".claude" / "commands")`; emit clear "re-run `sw init`" remediation.
15. MEDIUM → `src/superpower_workflow/cli.py:1183` (and matching read sites at cli.py:678, 805, 843, 882, 1182, 1284) — Centralize config loading in a helper that checks `schema_version`.
16. MEDIUM → `src/superpower_workflow/cli.py:383,398,520` — Replace non-atomic writes with tmp + `os.replace` per CLAUDE.md convention.
17. MEDIUM → `src/superpower_workflow/cli.py:419` — Narrow bare `except Exception: pass` to expected exceptions and emit stderr warning.
18. MEDIUM → `src/superpower_workflow/cli.py:1113,1130` — Use `[sys.executable, "-m", "pip", ...]` instead of `["pip", ...]`.
19. MEDIUM → `src/superpower_workflow/onboard.py:114` — Move existing-workflow.json detection ABOVE the `if not interactive: return cfg` early-return; change `OnboardConfig.accept_existing` default to a sentinel like `""` set to `"abort"`/`"replace"`/`"merge"` only via interactive prompt.
20. MEDIUM → `src/superpower_workflow/onboard.py:119` — Either implement `merge` (read existing JSON, overlay wizard fields) or remove `merge` from choices.
21. MEDIUM → Add `test_quality_gates_e2e.py` exercising orchestrator gate-execution → `.quality-gate-results.json` → convergence_gate hook.

LOW (cleanup pass):
22. LOW → `src/superpower_workflow/cli.py:396` — Replace substring `e not in existing` with exact-line match against `set(existing.splitlines())`.
23. LOW → `src/superpower_workflow/cli.py:648,989` — Use `_resolve_telemetry_path` helper; honor `config.telemetry.enabled`.
24. LOW → `src/superpower_workflow/cli.py:412` — Gate `_install_project_local` behind `if not minimal:` or add `--no-install-skills`; document `bypassPermissions` default in `--minimal` help.
25. LOW → `src/superpower_workflow/onboard.py:137-139` — Validate `n in 1..len(specs)` before indexing; on out-of-range, re-prompt or error rather than coerce to literal path.
26. LOW → `src/superpower_workflow/onboard.py` (non-interactive branch) — Set `cfg.spec_path = (str(specs[0].relative_to(project_root)) if specs else "spec.md")` when interactive=False.
27. LOW → `src/superpower_workflow/recommender.py:63` — Distinguish file-missing vs unreadable; stderr-warn for OSError.
28. LOW → `src/superpower_workflow/statusline.py:21,36,47,65` — Use `DEFAULT_STATUSLINE_PATH` or delete; add `schema_version` check; clamp `cur_ms+1` to `total`; atomic write via tmp + `os.replace`.
29. LOW → `src/superpower_workflow/project_detect.py:42,76,116` — Drop None values in quality_gates at copy-time; remove Java/Ruby from `_LANG_MARKERS` until templates exist (or add templates); switch existence check to `.is_file()`.
30. LOW → `src/superpower_workflow/cli.py:1019` — Assert `full.is_relative_to(project_root.resolve())` in `_cmd_lint_spec`.
31. LOW → `_assets/commands/sw-status.md` — Add one-line preamble: "Run from project root; if `sw` is not on PATH, use `python -m superpower_workflow status`."
32. LOW → `scripts/complexity_audit.py:79` — Wrap `relative_to` in try/except; fall back to `os.path.relpath`.
33. LOW → `CHANGELOG.md` — Fix v1.1.8 test-count breakdown (line 100), v1.2.0 functions-audited count (line 58), v1.1.9 provisional-pick wording (line 67), v1.3.0 skill auto-invocation claim (line 12), v1.3.0 wheel-asset-check claim (line 34). Either scaffold v1.1.8.1/v1.1.9.1/v1.3.1 deferrals or drop explicit version targets.
34. LOW → `tests/test_recommender.py:94`, `tests/test_project_detect.py:87`, `tests/test_onboard.py:93,101`, `tests/test_trust_but_verify_pipeline.py:26`, `tests/test_complexity_audit.py:58`, `tests/test_statusline.py:22`, `tests/test_init_quality_gates.py:32` — Replace tautologies, rename misleading tests, add missing edge-case coverage.

## Per-release verdict

v1.1.8: NEEDS_FIX (2 safety HIGHs — path traversal in `sw clean`, PID-reuse in `sw server stop`; 4 MEDIUM non-atomic-write violations; multiple missing `schema_version` checks; doctor not extended; default-flip upgrade path absent)
v1.1.9: NEEDS_FIX (2 HIGHs — onboard/init parity, tautological recommender test; convergence-block parity gap; recommender quality_score formula collapse; `merge` is dead choice)
v1.2.0: NEEDS_FIX (3 HIGHs — complexity_audit elif over-count, TrustButVerifyPipeline signature drift, _emit_spec_lint_event integration shared with v1.1.7/8/9; complexity_audit AST coverage gaps for `ast.Match`/async; pipeline behavior tests give false confidence)
v1.3.0: NEEDS_FIX (1 confirmed integration HIGH carried from v1.1.7; 1 completeness HIGH — code-quality-loop broken config key; 1 completeness HIGH — statusline unwired dead code; 4 auto-skills with no Python integration despite CHANGELOG implying orchestrator-driven invocation; doctor.py not extended; CI wheel-asset verifier too loose)

No release receives SAFE_TO_KEEP. No release is a REGRESSION in the strict sense (no orchestrator hot-path bug was introduced and confirmed). All four releases require a follow-up patch before they should be considered production-ready.
