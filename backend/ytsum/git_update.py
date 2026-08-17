from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


class GitUpdateError(RuntimeError):
    """A user-facing failure while inspecting or updating the source checkout."""


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise GitUpdateError(
            "Git is not installed or is unavailable to the application."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise GitUpdateError(
            "Git did not finish in time. Check your network connection and try again."
        ) from error


def _failure(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    return (result.stderr or result.stdout or fallback).strip().splitlines()[-1]


def _repository_ready() -> tuple[bool, str | None]:
    result = _git("rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != "true":
        return (
            False,
            "This installation is not a Git working tree, so source updates are unavailable.",
        )
    return True, None


def source_update_status(fetch: bool = True) -> dict:
    """Return an actionable, read-only status of this checkout and its upstream."""
    is_repository, diagnostic = _repository_ready()
    if not is_repository:
        return {
            "available": False,
            "clean": None,
            "branch": None,
            "upstream": None,
            "ahead": 0,
            "behind": 0,
            "can_pull": False,
            "diagnostic": diagnostic,
        }

    status = _git("status", "--porcelain=v1")
    if status.returncode != 0:
        raise GitUpdateError(
            _failure(status, "Could not inspect the Git working tree.")
        )
    clean = not status.stdout.strip()
    branch_result = _git("branch", "--show-current")
    branch = branch_result.stdout.strip() or "detached HEAD"
    upstream_result = _git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    if upstream_result.returncode != 0:
        return {
            "available": True,
            "clean": clean,
            "branch": branch,
            "upstream": None,
            "ahead": 0,
            "behind": 0,
            "can_pull": False,
            "diagnostic": "This branch has no upstream remote. Configure one before updating.",
        }

    upstream = upstream_result.stdout.strip()
    fetch_diagnostic = None
    if fetch:
        fetched = _git("fetch", "--quiet", "--prune", timeout=90)
        if fetched.returncode != 0:
            fetch_diagnostic = f"Could not refresh upstream information: {_failure(fetched, 'git fetch failed.')}"

    counts = _git("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if counts.returncode != 0:
        raise GitUpdateError(
            _failure(counts, "Could not compare this branch with its upstream.")
        )
    ahead, behind = (int(value) for value in counts.stdout.split())
    if not clean:
        diagnostic = "Local changes detected. Source updates are blocked until the working tree is clean."
    elif fetch_diagnostic:
        diagnostic = fetch_diagnostic
    elif behind:
        diagnostic = f"{behind} upstream commit(s) are available."
    elif ahead:
        diagnostic = "This branch contains local commits not yet in its upstream."
    else:
        diagnostic = "The source checkout is up to date."
    return {
        "available": True,
        "clean": clean,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "can_pull": clean and behind > 0 and not fetch_diagnostic,
        "diagnostic": diagnostic,
    }


def pull_source_update() -> dict:
    """Fast-forward the checkout after re-checking its safety constraints."""
    status = source_update_status(fetch=True)
    if not status["available"]:
        raise GitUpdateError(status["diagnostic"])
    if not status["clean"]:
        raise GitUpdateError(
            "Local changes detected. Commit, stash, or discard them before updating."
        )
    if not status["upstream"]:
        raise GitUpdateError("This branch has no upstream remote.")
    if not status["behind"]:
        return {**status, "updated": False, "restart_required": False}

    result = _git("pull", "--ff-only", timeout=180)
    if result.returncode != 0:
        raise GitUpdateError(
            _failure(result, "git pull failed; no restart was performed.")
        )
    return {
        **source_update_status(fetch=False),
        "updated": True,
        "restart_required": True,
    }
