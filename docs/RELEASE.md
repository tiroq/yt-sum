# Release policy

This project prepares releases locally and deliberately. The automation has no publish, deploy, tag, push, GitHub-release, or package-upload command. A release becomes public only when a maintainer separately performs the explicit Git actions after reviewing the prepared commit.

## Prerequisites

- Node.js 22.13 or later and npm.
- Python 3.11 or later.
- [`just`](https://github.com/casey/just) and [`uv`](https://docs.astral.sh/uv/).

`uv.lock` and `package-lock.json` are committed release inputs. Do not update either as part of `prepare-release`; dependency changes are reviewed separately.

## Everyday gates

Run these from the repository root:

```bash
just install   # npm ci + uv sync --locked; creates only local environments
just check     # lint, Python bytecode compilation, whitespace errors
just test      # JavaScript and Python tests
just build     # local production web build
just verify    # check, test, build, and version consistency
```

`just install` uses the committed lockfiles and fails if the Python lockfile is stale. `check`, `test`, and `build` do not edit tracked source files. The build output remains local and is ignored by Git.

## Versioning

Use Semantic Versioning (`MAJOR.MINOR.PATCH`, with optional prerelease/build suffix). The Node package, `package-lock.json`, and Python project must carry exactly the same version.

```bash
just version
just version-check
just version-set 0.2.0
```

`version-set` is intentionally a local metadata change: it updates `package.json`, `package-lock.json`, and `pyproject.toml`, validates that they match, and creates neither a tag nor a remote change.

## Preparing a release

Start from a clean worktree on the intended release commit. The command below runs every gate first, then changes local version metadata and creates a notes draft. It stops on the first failure and refuses to overwrite existing notes.

```bash
just prepare-release 0.2.0
```

This produces `docs/releases/v0.2.0.md`. Review and edit the notes: group user-visible changes, call out migrations or compatibility changes, and remove irrelevant commit messages. Then review the diff, commit it, and only afterwards explicitly create and push the annotated `v0.2.0` tag using your normal repository workflow.

## Release checklist

1. Confirm dependency lockfiles are intentional and committed.
2. Run `just install` and `just verify` on a clean checkout.
3. Run `just prepare-release <version>`.
4. Review the version diff and `docs/releases/v<version>.md`; commit both.
5. Have a maintainer explicitly tag and publish through the chosen hosting workflow.
6. Verify the published artifact and update the release notes if necessary.

No command in this repository performs steps 5 or 6 automatically.
