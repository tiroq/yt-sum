# Copilot instructions for YT Sum

This repo is a local-first YouTube transcript and summarization app. The main boundaries are:

- Frontend: `app/` (Next.js/React UI)
- Backend: `backend/ytsum/` (FastAPI app, processing pipeline, storage, local library logic)
- Browser extension: `browser-extension/` (Manifest V3 extension)
- Tests: `tests/*.test.mjs` for JavaScript, `tests/python/` for Python
- Project docs: `README.md`, `docs/`, and `Justfile`

## Working rules

- Preserve current user-facing behavior unless the task explicitly asks for a behavior change.
- Prefer tests that exercise public APIs, backend storage flows, and user-visible behavior rather than isolated implementation details.
- Do not add superficial tests that only execute code without assertions.
- Do not weaken production code or relax assertions to satisfy coverage.
- Do not skip, xfail, or delete tests to hide regressions.
- Mock only external boundaries such as the network, filesystem roots, subprocesses, clocks, or OS APIs; avoid mocking the unit under test.
- Keep comments and docs in English.
- Run the relevant validation before finishing, using the smallest check that covers the changed behavior.

## Repository workflow

Use the repo-root commands in the order that matches the change:

```bash
just check
just test
just coverage
just build
```

Useful local runtime commands:

```bash
just start
just stop
just api-restart
```

If coverage setup is missing in the local Python environment, install it with:

```bash
uv sync --locked --extra dev
```

## Architecture and conventions

- Start with the product docs in [README.md](../README.md) and the detailed specs under [docs](../docs) before changing behavior that affects file formats, pipeline semantics, or the API contract.
- For product behavior changes, check [docs/SPECIFICATION.md](../docs/SPECIFICATION.md), [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md), and [docs/FILE_FORMAT.md](../docs/FILE_FORMAT.md) first.
- Keep changes small and aligned with the existing local-first architecture: the app stores data in the user-selected library folder and rebuilds local indexes when needed.
- When a fix affects transcript processing, queueing, or library metadata, prefer end-to-end or public-surface tests in `tests/` and `tests/python/`.

## Coverage expectations

The project is configured for strict coverage gates:

- JavaScript coverage: line, branch, and function coverage for exercised files via `scripts/js-coverage-gate.mjs`
- Python coverage: branch-aware coverage for `backend/` via `pyproject.toml`

Use the incremental workflow:

1. Run the focused test file or relevant suite.
2. Run `just coverage` when the behavior is ready.
3. Add or improve tests for the smallest uncovered behavior cluster before broadening scope.

This repo intentionally refuses cheap coverage-only changes; fix the actual behavior and keep tests meaningful.
