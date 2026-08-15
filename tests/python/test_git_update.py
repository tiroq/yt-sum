import subprocess

import pytest

from ytsum import git_update


def result(args: tuple[str, ...], stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], returncode, stdout=stdout, stderr="")


def test_status_reports_clean_checkout_and_upstream_commits(monkeypatch) -> None:
    replies = iter([
        result(("rev-parse", "--is-inside-work-tree"), "true\n"),
        result(("status", "--porcelain=v1")),
        result(("branch", "--show-current"), "main\n"),
        result(("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"), "origin/main\n"),
        result(("fetch", "--quiet", "--prune")),
        result(("rev-list", "--left-right", "--count", "HEAD...origin/main"), "2\t3\n"),
    ])
    monkeypatch.setattr(git_update, "_git", lambda *args, **_: next(replies))

    status = git_update.source_update_status()

    assert status["clean"] is True
    assert status["ahead"] == 2
    assert status["behind"] == 3
    assert status["can_pull"] is True


def test_pull_refuses_dirty_tree_without_running_git_pull(monkeypatch) -> None:
    monkeypatch.setattr(git_update, "source_update_status", lambda fetch=True: {
        "available": True, "clean": False, "upstream": "origin/main", "behind": 4,
    })

    with pytest.raises(git_update.GitUpdateError, match="Local changes"):
        git_update.pull_source_update()
