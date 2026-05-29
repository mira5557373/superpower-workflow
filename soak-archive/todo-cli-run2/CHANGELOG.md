### Features

- feat: implement TodoStore.list_todos with done filtering (116d552)
- feat: implement TodoStore.remove to delete todos by ID (90c4c4e)
- feat: implement TodoStore.done to mark todos complete (f1078aa)
- feat: implement TodoStore.add with auto-incrementing IDs (ea3ce8b)
- feat: implement TodoStore.save with atomic write-then-rename (9bc7aa1)
- feat: implement TodoStore.load to read todos from JSON (ee8db9a)
- feat: implement TodoStore initialization with file creation (7b51af1)
- feat: add Todo to_dict and from_dict serialization (fcee059)
- feat: implement Todo dataclass with defaults (ee97f13)
- feat: add TDD implementation plan for M1-storage (e05bdb8)

### Bug Fixes

- fix: strengthen rm alias error assertions to match remove/done tests (37b97d3)
- fix: add rm alias and post-impl review fixes for M2-cli (bebab68)
- fix: post-impl and production review fixes for M1-storage (811786f)

### Refactoring

- refactor: add store fixture to conftest and simplify tests (c22d9b7)

### Documentation

- docs: add TDD implementation plan for M3-done-rm (2cb23b1)
- docs: update generated documentation (11a7b72)
- docs: add M2-cli TDD implementation plan (a1bfb6f)
- docs: update generated documentation (ad618a8)
- docs: add CLAUDE.md with project conventions and module map (da494c5)

### Tests

- test: verify rm on already-removed todo returns exit 1 (74b2444)
- test: verify done on removed todo returns exit 1 (67ed625)
- test: verify done and remove on corrupted store return clean errors (1a1c59f)
- test: verify remove preserves other todos in order (0fe9416)
- test: verify removing a done todo succeeds (dad5d61)
- test: verify done on already-done todo is idempotent (04ffe3f)
- test: harden remove-unknown-id with error format and no stdout assertions (7293ea2)
- test: add full lifecycle integration test (add/done/list/rm) (c8ae092)
- test: harden done-unknown-id with error format and no stdout assertions (9ec52a3)
- test: harden done-hides-from-default-list with exit code assertion (1b14ed7)
- test: verify done preserves text and created_at fields (420d5fd)
- test: add parser-level unit test for rm alias (9597e31)
- test: add parser-level unit test for remove subcommand (ff52d36)
- test: add parser-level unit test for done subcommand (fe5e4cd)
- test: add corrupted store on add and store init error tests (2cfcfc0)
- test: add deterministic output test for list command (474b85f)
- test: update list tests to use store API for done item setup (6a668d3)
- test: add monotonic ID generation test for add command (52498f8)
- test: add ISO-8601 validation to add command output test (5252924)
- test: add argparse parser structure tests (8f90f4f)
- test: add unit test for _format_todo output helper (4381cd8)
- test: add edge case and crash resilience tests (2e204ea)
- test: add TodoStore.list_todos tests for filtering (red) (546cbb3)
- test: add ID generation tests for incrementing and no-reuse (9bbe513)
- test: add TodoStore.remove tests for deletion and error cases (red) (6c2541d)
- test: add TodoStore.done tests for status flip and error cases (red) (177a424)
- test: add TodoStore.add tests for creation and persistence (red) (6e4e1a9)
- test: add TodoStore.save atomic write tests (red) (24457d1)
- test: add TodoStore.load tests for empty and populated store (red) (e62659d)
- test: add TodoStore init and file creation tests (red) (e41fb29)
- test: add Todo serialization round-trip tests (red) (e938244)
- test: add Todo dataclass field and default tests (red) (e98b5eb)

### Chores

- chore: scaffold project with pyproject.toml and package skeleton (c63244c)
- chore: gitignore lock aux files (fd91b06)
- chore: sw init (501c971)

### Other

- soak: gitignore reports/ + untrack gap-report (a9afe3d)
- soak: gitignore .coverage (cb5f6f7)
- soak: add M2-cli + M3-done-rm (6d66c61)
- soak: switch to opus + raise cap to 30 (3dbf727)
- init: spec (6915b5f)