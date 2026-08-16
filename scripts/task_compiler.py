#!/usr/bin/env python3
"""
task_compiler.py

Generate a detailed engineering task from a short request using any
OpenAI-compatible Chat Completions API.

The script is intentionally dependency-light and uses only the Python
standard library.

Environment variables:
    TASK_API_BASE_URL   Base API URL, for example https://api.example.com/v1
    TASK_API_KEY        API key
    TASK_MODEL          Model name
    TASK_OUTPUT_DIR     Optional output directory, default: .tasks/generated
    TASK_MAX_FILES      Optional maximum number of repository files in discovery
    TASK_MAX_FILE_BYTES Optional maximum bytes read from any single file

Examples:
    export TASK_API_BASE_URL="https://api.example.com/v1"
    export TASK_API_KEY="..."
    export TASK_MODEL="some-model"

    python task_compiler.py "Fix duplicated orders returned by the API"

    python task_compiler.py \
        --base-url https://api.example.com/v1 \
        --api-key "$MY_KEY" \
        --model some-model \
        "Fix duplicated orders returned by the API"
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_OUTPUT_DIR = ".tasks/generated"
DEFAULT_MAX_FILES = 1200
DEFAULT_MAX_FILE_BYTES = 40_000
DEFAULT_MAX_SELECTED_FILES = 16
DEFAULT_MAX_TOTAL_CONTEXT_BYTES = 220_000
DEFAULT_TIMEOUT_SECONDS = 120

DEFAULT_IGNORES = {
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "coverage",
    ".coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "__pycache__",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    "tmp",
    "temp",
}

BINARY_EXTENSIONS = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".bmp",
    ".class",
    ".db",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lockb",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".obj",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".ttf",
    ".woff",
    ".woff2",
    ".webp",
    ".zip",
}

IMPORTANT_FILENAMES = {
    "README",
    "README.md",
    "README.rst",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "Pipfile",
    "poetry.lock",
    "uv.lock",
    "go.mod",
    "go.sum",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
}


@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    output_dir: Path
    max_files: int
    max_file_bytes: int
    max_selected_files: int
    max_total_context_bytes: int
    timeout_seconds: int
    temperature: float
    repo: Path


@dataclass
class FileInfo:
    path: str
    size: int


def run_command(args: Sequence[str], cwd: Path, timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def find_repo_root(start: Path) -> Path:
    root = run_command(["git", "rev-parse", "--show-toplevel"], start)
    if root:
        return Path(root).resolve()
    return start.resolve()


def should_ignore(path: Path, repo: Path) -> bool:
    try:
        relative = path.relative_to(repo)
    except ValueError:
        return True

    for part in relative.parts:
        if part in DEFAULT_IGNORES:
            return True

    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True

    return False


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return False
    try:
        with path.open("rb") as fh:
            sample = fh.read(2048)
    except OSError:
        return False
    return b"\x00" not in sample


def list_repository_files(repo: Path, max_files: int) -> list[FileInfo]:
    git_files = run_command(["git", "ls-files", "-co", "--exclude-standard"], repo)
    paths: list[Path]

    if git_files:
        paths = [repo / line for line in git_files.splitlines() if line.strip()]
    else:
        paths = [p for p in repo.rglob("*") if p.is_file()]

    result: list[FileInfo] = []
    for path in paths:
        if len(result) >= max_files:
            break
        if should_ignore(path, repo) or not is_probably_text(path):
            continue
        try:
            size = path.stat().st_size
            relative = str(path.relative_to(repo))
        except OSError:
            continue
        result.append(FileInfo(path=relative, size=size))

    return result


def repository_metadata(repo: Path) -> str:
    branch = run_command(["git", "branch", "--show-current"], repo)
    status = run_command(["git", "status", "--short"], repo)
    recent = run_command(
        ["git", "log", "-8", "--pretty=format:%h %ad %s", "--date=short"], repo
    )
    top_level = sorted(
        p.name for p in repo.iterdir()
        if p.name != ".git"
    )

    return textwrap.dedent(
        f"""
        Repository: {repo.name}
        Branch: {branch or "(unknown)"}

        Top-level entries:
        {chr(10).join(f"- {name}" for name in top_level[:100])}

        Git status:
        {status or "(clean or unavailable)"}

        Recent commits:
        {recent or "(unavailable)"}
        """
    ).strip()


def compact_file_index(files: Sequence[FileInfo]) -> str:
    lines = []
    for item in files:
        marker = " *" if Path(item.path).name in IMPORTANT_FILENAMES else ""
        lines.append(f"{item.path} ({item.size} bytes){marker}")
    return "\n".join(lines)


def api_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def call_chat_completions(
    cfg: Config,
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
) -> str:
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature if temperature is None else temperature,
    }

    request = urllib.request.Request(
        api_url(cfg.base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"API request failed with HTTP {exc.code}: {body[:2000]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc

    try:
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Unexpected API response format. "
            f"First 2000 bytes: {raw[:2000]}"
        ) from exc


def parse_json_object(text: str) -> dict:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise RuntimeError(f"Model did not return valid JSON: {text[:2000]}")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Model did not return valid JSON: {text[:2000]}"
            ) from exc


def select_relevant_files(
    cfg: Config,
    request_text: str,
    files: Sequence[FileInfo],
    metadata: str,
) -> tuple[list[str], list[str]]:
    system_prompt = """
You are a repository triage assistant.

Your only job is to select repository files that are likely to contain
evidence needed to convert a short engineering request into a precise task.

Do not solve the task.
Do not invent files.
Prefer a small, high-signal set of files.
Include tests, interfaces, configs, schemas, and documentation when relevant.

Return JSON only with this exact shape:

{
  "files": ["path/one", "path/two"],
  "search_terms": ["term1", "term2"]
}

Rules:
- Select at most 16 files.
- Every selected path must appear in the provided repository file index.
- search_terms should contain 3-10 concrete strings that may help locate related code.
- If the request is ambiguous, still select the most likely discovery files.
""".strip()

    user_prompt = f"""
SHORT REQUEST:
{request_text}

REPOSITORY METADATA:
{metadata}

FILE INDEX:
{compact_file_index(files)}
""".strip()

    response = call_chat_completions(
        cfg,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )
    data = parse_json_object(response)

    valid_paths = {item.path for item in files}
    selected = [
        path for path in data.get("files", [])
        if isinstance(path, str) and path in valid_paths
    ][: cfg.max_selected_files]

    search_terms = [
        term.strip()
        for term in data.get("search_terms", [])
        if isinstance(term, str) and term.strip()
    ][:10]

    return selected, search_terms


def grep_related_files(
    repo: Path,
    search_terms: Sequence[str],
    known_files: set[str],
    limit: int = 12,
) -> list[str]:
    result: list[str] = []

    for term in search_terms:
        if len(result) >= limit:
            break

        output = run_command(
            ["git", "grep", "-l", "-I", "-F", "--", term],
            repo,
            timeout=15,
        )
        if not output:
            continue

        for path in output.splitlines():
            if path in known_files and path not in result:
                result.append(path)
                if len(result) >= limit:
                    break

    return result


def add_important_files(
    selected: list[str],
    files: Sequence[FileInfo],
    limit: int,
) -> list[str]:
    result = list(selected)
    for item in files:
        if len(result) >= limit:
            break
        if Path(item.path).name in IMPORTANT_FILENAMES and item.path not in result:
            result.append(item.path)
    return result


def read_file_for_context(path: Path, max_bytes: int) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return f"[Unable to read file: {exc}]"

    truncated = len(raw) > max_bytes
    raw = raw[:max_bytes]
    text = raw.decode("utf-8", errors="replace")

    if truncated:
        text += f"\n\n[TRUNCATED after {max_bytes} bytes]"

    return text


def build_repository_context(
    cfg: Config,
    selected_paths: Sequence[str],
) -> str:
    chunks: list[str] = []
    total = 0

    for relative in selected_paths:
        path = cfg.repo / relative
        if not path.is_file() or should_ignore(path, cfg.repo):
            continue

        content = read_file_for_context(path, cfg.max_file_bytes)
        block = f"\n===== FILE: {relative} =====\n{content}\n"

        block_size = len(block.encode("utf-8"))
        if total + block_size > cfg.max_total_context_bytes:
            remaining = cfg.max_total_context_bytes - total
            if remaining <= 1000:
                break
            block = block.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
            block += "\n[GLOBAL CONTEXT LIMIT REACHED]\n"

        chunks.append(block)
        total += len(block.encode("utf-8"))

        if total >= cfg.max_total_context_bytes:
            break

    return "".join(chunks).strip()


def generate_task(
    cfg: Config,
    request_text: str,
    metadata: str,
    repository_context: str,
    selected_paths: Sequence[str],
) -> str:
    system_prompt = """
You are an expert software engineering task compiler.

You do NOT implement the requested change.
You convert a short engineering request plus verified repository evidence
into a self-contained implementation task for another coding agent.

Core rules:
1. Never invent repository facts.
2. Every repository-specific claim must be supported by the supplied context.
3. Clearly distinguish verified facts, assumptions, and unknowns.
4. Do not prescribe unnecessary architecture changes.
5. Follow YAGNI: propose the smallest change that satisfies the request.
6. Preserve existing project conventions when the evidence shows them.
7. Include enough repository context that the implementation agent should not
   need broad repository exploration before starting.
8. Do not copy huge source files into the task.
9. Prefer exact file paths, symbols, test names, commands, and interfaces.
10. If the request is ambiguous, capture ambiguity under Open Questions rather
    than silently guessing.

Return Markdown only.

Use this structure exactly:

# Task: <concise task title>

## Original Request

## Problem Statement

## Repository Evidence

## Relevant Files

## Current Behavior

## Expected Behavior

## Scope

### In Scope

### Out of Scope

## Implementation Constraints

## Suggested Implementation Approach

## Acceptance Criteria

Use Markdown checkboxes for acceptance criteria.

## Test Requirements

## Edge Cases

## Non-Goals

## Risks and Assumptions

## Open Questions

## Definition of Done

The resulting document must be actionable by a strong coding model without
requiring the original short request or this system prompt.
""".strip()

    user_prompt = f"""
ORIGINAL SHORT REQUEST:
{request_text}

REPOSITORY METADATA:
{metadata}

FILES SELECTED FOR ANALYSIS:
{chr(10).join(f"- {path}" for path in selected_paths)}

VERIFIED REPOSITORY CONTEXT:
{repository_context}
""".strip()

    return call_chat_completions(
        cfg,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=cfg.temperature,
    )


def slugify(text: str, max_length: int = 60) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return (text[:max_length].rstrip("-") or "task")


def extract_title(markdown: str) -> str:
    match = re.search(r"^# Task:\s*(.+?)\s*$", markdown, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    return "generated-task"


def save_task(cfg: Config, task_markdown: str) -> Path:
    output_dir = cfg.repo / cfg.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    title = extract_title(task_markdown)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}-{slugify(title)}.md"
    output = output_dir / filename
    output.write_text(task_markdown.rstrip() + "\n", encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile a short engineering request into a detailed task."
    )
    parser.add_argument(
        "request",
        nargs="+",
        help="Short engineering request.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("TASK_API_BASE_URL", ""),
        help="OpenAI-compatible API base URL. Env: TASK_API_BASE_URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("TASK_API_KEY", ""),
        help="API key. Env: TASK_API_KEY",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("TASK_MODEL", ""),
        help="Model name. Env: TASK_MODEL",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository path. Default: current directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("TASK_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
        help=f"Output directory relative to repo. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=int(os.getenv("TASK_MAX_FILES", DEFAULT_MAX_FILES)),
        help="Maximum number of repository files included in discovery index.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=int(
            os.getenv("TASK_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES)
        ),
        help="Maximum bytes read from a selected repository file.",
    )
    parser.add_argument(
        "--max-selected-files",
        type=int,
        default=DEFAULT_MAX_SELECTED_FILES,
        help="Maximum files sent as repository context.",
    )
    parser.add_argument(
        "--max-total-context-bytes",
        type=int,
        default=DEFAULT_MAX_TOTAL_CONTEXT_BYTES,
        help="Maximum total repository context bytes.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="API request timeout in seconds.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Generation temperature. Default: 0.2",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show selected repository files without generating the task.",
    )
    return parser.parse_args()


def validate_config(args: argparse.Namespace, repo: Path) -> Config:
    missing = []
    if not args.base_url:
        missing.append("TASK_API_BASE_URL / --base-url")
    if not args.api_key:
        missing.append("TASK_API_KEY / --api-key")
    if not args.model:
        missing.append("TASK_MODEL / --model")

    if missing:
        raise SystemExit(
            "Missing required configuration:\n  - " + "\n  - ".join(missing)
        )

    return Config(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        output_dir=Path(args.output_dir),
        max_files=max(1, args.max_files),
        max_file_bytes=max(1000, args.max_file_bytes),
        max_selected_files=max(1, args.max_selected_files),
        max_total_context_bytes=max(5000, args.max_total_context_bytes),
        timeout_seconds=max(5, args.timeout),
        temperature=args.temperature,
        repo=repo,
    )


def main() -> int:
    args = parse_args()
    request_text = " ".join(args.request).strip()

    if not request_text:
        print("Request must not be empty.", file=sys.stderr)
        return 2

    repo = find_repo_root(Path(args.repo).resolve())
    cfg = validate_config(args, repo)

    print(f"Repository: {repo}")
    print(f"Model: {cfg.model}")
    print("Scanning repository...")

    files = list_repository_files(repo, cfg.max_files)
    if not files:
        print("No readable repository files found.", file=sys.stderr)
        return 2

    metadata = repository_metadata(repo)

    print(f"Discovered {len(files)} text files.")
    print("Selecting relevant files with the model...")

    selected, search_terms = select_relevant_files(
        cfg,
        request_text,
        files,
        metadata,
    )

    known_files = {item.path for item in files}
    grep_matches = grep_related_files(
        repo,
        search_terms,
        known_files,
        limit=cfg.max_selected_files,
    )

    merged: list[str] = []
    for path in [*selected, *grep_matches]:
        if path not in merged:
            merged.append(path)
        if len(merged) >= cfg.max_selected_files:
            break

    merged = add_important_files(
        merged,
        files,
        cfg.max_selected_files,
    )

    print("Selected repository context:")
    for path in merged:
        print(f"  - {path}")

    if search_terms:
        print("Search terms:")
        for term in search_terms:
            print(f"  - {term}")

    if args.dry_run:
        return 0

    repository_context = build_repository_context(cfg, merged)
    if not repository_context:
        print(
            "Could not build repository context from selected files.",
            file=sys.stderr,
        )
        return 2

    print("Generating task...")
    task_markdown = generate_task(
        cfg,
        request_text,
        metadata,
        repository_context,
        merged,
    )

    output = save_task(cfg, task_markdown)
    print(f"Task created: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
