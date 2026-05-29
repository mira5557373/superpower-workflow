# Ultrathink Gap Analysis Heuristics

## Plan Review Heuristics

### Architecture
- **File paths:** Do all referenced files exist? Are relative paths correct? Do imports resolve?
- **Import consistency:** Are paths consistent across all tasks (e.g., `from mymodule.submodule import X` vs `from mymodule import submodule; submodule.X`)?
- **Circular dependencies:** Can Task A depend on Task B if B depends on A? Trace dependency graph.
- **Codebase patterns:** Does the plan follow established patterns? If existing code uses `async def`, do new tasks also use async? If existing code uses `pathlib.Path`, does plan match?

### Completeness
- **Feature coverage:** Does the spec define each feature? Does the plan have a task for each feature? Are all acceptance criteria addressed?
- **Edge cases:** Are error cases handled? What about empty input, missing files, network timeouts, permission denied? Are they covered?
- **Integration points:** Does this plan integrate with prior milestones? Are there missing dependencies? Does it break existing APIs?
- **Backwards compatibility:** If modifying existing code, are old callers still supported?

### Testability
- **Test tasks:** Does every implementation task have a corresponding test task? Are tests scheduled after implementation?
- **Behavior verification:** Do tests verify behavior, not implementation? Bad: "assert calls function X". Good: "assert output is Y when input is Z".
- **Edge case coverage:** Do tests cover happy path and error paths? Do they test boundaries?
- **Test independence:** Can tests run in any order? Are there shared fixtures that could hide race conditions?

### Task Quality
- **Single responsibility:** Does each task do one thing? Bad: "implement parser and validator and error handler". Good: "implement parser; implement validator; implement error handler".
- **Acceptance criteria:** Are criteria clear and measurable? Bad: "works well". Good: "parses valid JSON and rejects invalid JSON with specific error message at line:col".
- **Task ordering:** Are dependencies correct? Can Task B start before Task A completes? Would Task B be blocked?
- **Scope:** Is the task too big to complete in one session? Can it be split?

## Code Review Heuristics

### Correctness
- **Error paths:** Are all exceptions caught? Do error handlers prevent crashes? Are errors logged or surfaced?
- **Type mismatches:** Do function signatures match calls? Are types compatible (int vs str, list vs dict)?
- **Off-by-one:** Loop bounds correct? Array indices within range? String slicing end-inclusive or exclusive?
- **Async cancellation:** If using async/await, can tasks be cancelled cleanly? Are resources released on cancel?
- **Null/None handling:** Are None values checked before use? Can functions return None unexpectedly?

### Security
- **Path traversal:** Can user input construct paths like `../../sensitive_file`? Use `pathlib.Path.resolve()` to canonicalize.
- **Injection:** If constructing commands, SQL, or shell, is user input escaped/parameterized?
- **Secrets in code:** Are passwords, tokens, API keys hardcoded? Are they logged or printed?
- **Unvalidated input:** Are all user/external inputs validated before use (length, type, format, range)?
- **SSRF:** If making HTTP requests, can the URL come from untrusted input? Allowlist domains.
- **Spec guardrails:** Does code respect documented constraints (e.g., "max file size 10MB", "timeout 30s")?

### Testing
- **Function coverage:** Is every public function tested? Are private functions tested if complex?
- **Error path testing:** Are error cases tested? Do tests call functions with invalid input?
- **Assertion quality:** Do assertions verify behavior? Bad: `assert result`, `assert True`, `assert x is not None`. Good: `assert result == expected_value`, `assert isinstance(result, dict)`.
- **Test independence:** Do tests clean up? Can they run in parallel or in any order? Are there hidden dependencies (shared mocks, global state)?
- **Mock correctness:** Are mocks realistic? Do they return the same types as real code?

### Design
- **Single responsibility:** Does each module/class do one thing?
- **Interface clarity:** Are public functions/methods documented? Can callers understand behavior from signature?
- **Consistency:** Do similar tasks use similar patterns? If one async function uses `try/except`, do others?
- **Import resolution:** Do all imports work? Are circular imports present?
- **Cohesion:** Do related functions belong together? Or are they scattered?

### Performance
- **N+1 queries:** In loops, is the same query repeated? Move queries outside loops.
- **Unbounded collections:** Can lists/dicts grow without bounds? Will memory exhaust?
- **Blocking on async:** Is blocking code (e.g., `time.sleep()`, file I/O without `async`) called in async contexts?
- **Resource leaks:** Are files/connections closed? Are exceptions releasing resources (use `finally` or context managers)?
- **Connection limits:** If using connection pools, are limits configured? Can the pool exhaust?
- **Unnecessary work:** Is the same computation repeated? Can results be cached?

### Concurrency
- **Race conditions:** If multiple tasks access shared state, is it protected (locks, atomic operations)?
- **Deadlocks:** Can locks be acquired in different orders on different threads? Use consistent lock ordering.
- **Proper async/await:** Are all awaits present? Can a coroutine run without being awaited?
- **Task cancellation:** If tasks can be cancelled, are resources cleaned up? Use `try/finally`.
- **Pool exhaustion:** If using thread/async pools, can all tasks block waiting for each other?

## Severity Calibration

### Plan Review Severities

- **🔴 Critical:** References nonexistent module. Violates spec guardrail. Missing entire feature. Impossible task order (circular dependencies). Task references undefined variable.
- **🟡 Important:** Missing edge case documented in spec. Acceptance criteria unclear or unmeasurable. Task oversized (>4 subtasks, >4 hours). Integration point missing.
- **🟢 Acceptable:** Deferred to future milestone. Enhancement not in spec. Lower priority feature. Can be fixed in review.
- **🔵 Minor:** Wording, formatting, grammar. Markdown syntax. Comment clarity.

### Code Review Severities

- **🔴 Critical:** Runtime crash (uncaught exception, None access, index out of bounds). Security vulnerability (injection, path traversal, secret in logs). Spec guardrail violation (e.g., timeout exceeded, size limit violated). Test that doesn't verify behavior (assert True, assert result).
- **🟡 Important:** Missing error handling. Untested edge case. Design smell (inconsistent patterns, poor cohesion). Inconsistent with codebase conventions. Performance issue with evidence (N+1, unbounded growth).
- **🟢 Acceptable:** Optimization opportunity. Refactoring suggestion. Deferred feature. Code duplication <50 lines.
- **🔵 Minor:** Naming unclear. Comment missing. Import ordering. Trailing whitespace.

## Gap Quality Standards

### GOOD gap examples:
- "HttpClient.post() at client.py:87 doesn't retry on 5xx errors; spec requires exponential backoff."
- "Schema.validate() at validator.py:42 doesn't check for cyclic references in JSON; can cause infinite loop."
- "Task 5 depends on Task 3 output, but Task 3 acceptance criteria don't specify output format (JSON vs YAML)."
- "get_user() at users.py:15 returns dict with user password exposed; should exclude sensitive fields."

### BAD gap examples:
- "Error handling could be improved throughout."
- "Consider adding input validation."
- "May have performance implications."
- "Documentation could be enhanced."
- "Could benefit from more testing."

### The Rule:
If you cannot name a specific file, line, function, scenario, or constraint — it's not a gap. Delete it.

## Anti-Patterns (NEVER flag these)

The following are NOT gaps, even if true. Do not include them:

- "Could benefit from more comprehensive testing" (vague)
- "Consider adding input validation" (doesn't specify which input or constraint)
- "May have performance implications" (no evidence)
- "Documentation could be enhanced" (vague, not a concrete gap)
- "Think about edge cases" (doesn't name which edge cases)
- Any gap starting with "Consider...", "May...", "Could...", "Might...", "Should...", "Perhaps..."
- "Performance optimization" (without concrete evidence like "N+1 query", "unbounded growth")
- "Better error messages" (subjective, unless spec requires specific format)
- "Code could be refactored" (without naming what smells present)
