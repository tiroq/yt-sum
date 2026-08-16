# Copilot instructions for YT Sum

This project is a local-first YouTube transcript and summarization app with:

- a TypeScript/React frontend under `app/`;
- a Python FastAPI backend under `backend/ytsum/`;
- JavaScript tests under `tests/*.test.mjs`;
- Python tests under `tests/python/`;
- local automation through `Justfile`.

## Required engineering rules

- Preserve existing user-facing behavior unless the task explicitly asks for a behavior change.
- Prefer tests that exercise public functions, API endpoints, storage behavior, and user-visible flows.
- Do not add superficial tests that only execute lines without assertions.
- Do not weaken production code, delete behavior, or relax assertions to increase coverage.
- Do not skip, xfail, or remove tests to make a coverage gate pass.
- Do not mock the unit under test. Mock only external boundaries such as network, filesystem roots, subprocesses, time, or OS APIs.
- Keep comments in English.
- Run relevant checks before finishing.

## Standard commands

Use these commands from the repository root:

```bash
just test
just coverage
just check
```

If `just coverage` fails because the local Python dev environment does not yet include `coverage`, run:

```bash
uv sync --locked --extra dev
```

Then retry `just coverage`.

## Coverage policy

The target is 100% meaningful coverage:

- Python backend: branch-aware coverage configured in `pyproject.toml`.
- JavaScript frontend helpers/UI tests: line, branch, and function coverage checked by `scripts/js-coverage-gate.mjs`.

Coverage work must be incremental:

1. Run `just coverage`.
2. Identify the smallest uncovered behavior cluster.
3. Add or improve tests for that behavior.
4. Run the focused test file.
5. Run `just coverage` again.
6. Repeat until the gate passes.

When a file appears structurally untestable, first refactor toward pure helper functions or dependency injection, then test the extracted behavior. Keep refactors small and covered by tests.
