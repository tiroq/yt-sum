from __future__ import annotations

import subprocess


SERVICE_NAME = "com.ytsum.provider"


class KeychainError(RuntimeError):
    pass


def set_secret(account: str, secret: str) -> None:
    if not secret:
        delete_secret(account)
        return
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            SERVICE_NAME,
            "-a",
            account,
            "-w",
            secret,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise KeychainError(
            result.stderr.strip() or "Unable to store secret in macOS Keychain"
        )


def get_secret(account: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE_NAME, "-a", account, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def delete_secret(account: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", SERVICE_NAME, "-a", account],
        capture_output=True,
        text=True,
        check=False,
    )
