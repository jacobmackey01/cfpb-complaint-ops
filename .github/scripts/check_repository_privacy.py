"""Fail CI when a tracked path could expose complaint narratives or secrets."""

from __future__ import annotations

import subprocess
from pathlib import PurePosixPath


ALLOWED_ENV_FILES = {
    ".env.example",
    ".env.production.example",
    "frontend/.env.example",
}
ALLOWED_DATA_PATHS = {PurePosixPath("data/README.md")}
ALLOWED_DATA_PREFIXES = {
    PurePosixPath("data/requests"),
    PurePosixPath("data/manifests"),
}
ALLOWED_ARTIFACT_PATHS = {PurePosixPath("artifacts/README.md")}
ALLOWED_ARTIFACT_PREFIXES = {PurePosixPath("artifacts/public")}
BLOCKED_SUFFIXES = {
    ".csv",
    ".db",
    ".duckdb",
    ".jsonl",
    ".parquet",
    ".wal",
}
BLOCKED_FILENAMES = {".env", ".env.local", "complaints.jsonl.tmp"}


def tracked_paths() -> list[PurePosixPath]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"],
        text=True,
        encoding="utf-8",
    )
    return [PurePosixPath(item) for item in output.split("\0") if item]


def _under(path: PurePosixPath, prefixes: set[PurePosixPath]) -> bool:
    return any(path == prefix or prefix in path.parents for prefix in prefixes)


def violations(paths: list[PurePosixPath]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        path_text = path.as_posix()
        filename = path.name

        if filename.startswith(".env") and path_text not in ALLOWED_ENV_FILES:
            failures.append(f"tracked environment file: {path_text}")
        if filename in BLOCKED_FILENAMES:
            failures.append(f"tracked sensitive/runtime filename: {path_text}")

        if path.parts and path.parts[0] == "data":
            if path not in ALLOWED_DATA_PATHS and not _under(
                path, ALLOWED_DATA_PREFIXES
            ):
                failures.append(f"tracked non-allowlisted data path: {path_text}")
            if path.suffix.lower() in BLOCKED_SUFFIXES:
                failures.append(f"tracked row-level data file: {path_text}")

        if path.parts and path.parts[0] == "artifacts":
            if path not in ALLOWED_ARTIFACT_PATHS and not _under(
                path, ALLOWED_ARTIFACT_PREFIXES
            ):
                failures.append(f"tracked unreviewed artifact path: {path_text}")
            if path.suffix.lower() in BLOCKED_SUFFIXES:
                failures.append(f"tracked narrative-capable artifact: {path_text}")

        if path.parts and path.parts[0] == "work":
            failures.append(f"tracked scratch path: {path_text}")

    return failures


def main() -> int:
    failures = violations(tracked_paths())
    if failures:
        print("Repository privacy guard failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Repository privacy guard passed: tracked paths satisfy the allowlist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
