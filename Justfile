set shell := ["bash", "-euo", "pipefail", "-c"]

# List the available local-development and release commands.
default:
    @just --list

# Install the exact JavaScript dependency tree and the locked Python environment.
install:
    npm ci
    uv sync --locked --extra dev

# Run static checks without changing source files.
check:
    npm run lint
    .venv/bin/python -m compileall -q backend
    git diff --check

# Run JavaScript and Python test suites.
test:
    npm test
    .venv/bin/python -m pytest

# Build the production web artifact locally. Nothing is deployed.
build:
    npm run build

# Run all release gates in a deterministic order.
verify: check test build version-check

# Print the version declared by the JavaScript and Python project metadata.
version:
    @node -p "require('./package.json').version"
    @sed -nE 's/^version = "([^\"]+)"/\1/p' pyproject.toml | head -n 1

# Fail if package.json, package-lock.json, and pyproject.toml versions disagree.
version-check:
    @node_version="$(node -p 'require("./package.json").version')"; \
    lock_version="$(node -p 'require("./package-lock.json").version')"; \
    python_version="$(sed -nE 's/^version = \"([^\"]+)\"/\1/p' pyproject.toml | head -n 1)"; \
    test -n "$python_version"; \
    test "$node_version" = "$lock_version"; \
    test "$node_version" = "$python_version"; \
    printf 'Version %s is synchronized.\n' "$node_version"

# Update local version metadata only; it never creates a tag or pushes anything.
version-set version:
    @[[ "{{version}}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || { echo "Expected a SemVer version, got: {{version}}" >&2; exit 2; }
    npm version --no-git-tag-version --allow-same-version "{{version}}"
    sed -i.bak -E '0,/^version = \"[^\"]+\"/s//version = "{{version}}"/' pyproject.toml
    rm pyproject.toml.bak
    just version-check

# Create a local release-notes draft from commits since the latest version tag.
release-notes version:
    @[[ "{{version}}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || { echo "Expected a SemVer version, got: {{version}}" >&2; exit 2; }
    @mkdir -p docs/releases
    @test ! -e "docs/releases/v{{version}}.md" || { echo "docs/releases/v{{version}}.md already exists; refusing to overwrite it." >&2; exit 1; }
    @previous_tag="$(git describe --tags --abbrev=0 2>/dev/null || true)"; \
    range="${previous_tag:+$previous_tag..}HEAD"; \
    { \
      printf '# YT Sum v{{version}}\n\n'; \
      printf '> Draft generated locally. Review and edit before release.\n\n'; \
      printf '## Changes\n\n'; \
      git log --no-merges --format='- %s (%h)' "$range"; \
      printf '\n## Upgrade notes\n\n- No special steps identified.\n'; \
    } > "docs/releases/v{{version}}.md"

# Prepare a local release candidate: gates, version metadata, and notes only.
# It refuses a dirty worktree so release changes remain easy to review.
prepare-release version:
    @git diff --quiet && git diff --cached --quiet || { echo "Working tree is not clean; commit or stash changes first." >&2; exit 1; }
    just verify
    just version-set "{{version}}"
    just release-notes "{{version}}"
    @printf 'Prepared local release v%s. Review the diff, commit it, then tag/push manually.\n' "{{version}}"
