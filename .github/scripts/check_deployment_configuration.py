"""Fail CI when public deployment configuration drifts from the release contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_BACKEND_ENV = {
    "PUBLIC_DEMO_MODE": "false",
    "CFPB_LIVE_READ_MODE": "true",
    "CFPB_ALLOW_DEMO_FALLBACK": "false",
    "LLM_SUMMARY_ENABLED": "false",
    "LLM_MODEL": "gpt-5.6-luna",
}
EXPECTED_PRODUCTION_TEMPLATE = {
    **EXPECTED_BACKEND_ENV,
    "OPENAI_API_KEY": "",
}
FORBIDDEN_LOCKFILES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
}


def _json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot parse {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def _template_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _tracked_paths() -> list[str]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT, text=True, encoding="utf-8"
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"cannot inspect tracked paths: {exc}") from exc
    return [item for item in output.split("\0") if item]


def validate() -> list[str]:
    failures: list[str] = []
    root_vercel = _json(ROOT / "vercel.json")
    frontend_vercel = _json(ROOT / "frontend" / "vercel.json")

    builds = root_vercel.get("builds")
    if not (
        isinstance(builds, list)
        and builds
        and isinstance(builds[0], dict)
        and builds[0].get("src") == "app.py"
        and builds[0].get("use") == "@vercel/python"
    ):
        failures.append("root vercel.json must build app.py with @vercel/python")

    backend_env = root_vercel.get("env", {})
    if not isinstance(backend_env, dict):
        failures.append("root vercel.json env must be an object")
    else:
        for key, expected in EXPECTED_BACKEND_ENV.items():
            if backend_env.get(key) != expected:
                failures.append(f"root vercel.json env {key} must be {expected!r}")
        if backend_env.get("ALLOWED_ORIGINS") == "*":
            failures.append("root vercel.json must not wildcard ALLOWED_ORIGINS")
        if "OPENAI_API_KEY" in backend_env:
            failures.append("root vercel.json must not contain OPENAI_API_KEY")

    if frontend_vercel.get("framework") != "vite":
        failures.append("frontend/vercel.json must use the Vite framework")
    if "pnpm install --frozen-lockfile" not in str(
        frontend_vercel.get("installCommand", "")
    ):
        failures.append("frontend/vercel.json must use pnpm install --frozen-lockfile")
    if frontend_vercel.get("buildCommand") != "pnpm run build":
        failures.append("frontend/vercel.json must use pnpm run build")
    if frontend_vercel.get("outputDirectory") != "dist":
        failures.append("frontend/vercel.json must output dist")

    package = _json(ROOT / "frontend" / "package.json")
    if package.get("packageManager") != "pnpm@11.19.0":
        failures.append("frontend/package.json must pin pnpm@11.19.0")
    if not (ROOT / "frontend" / "pnpm-lock.yaml").is_file():
        failures.append("frontend/pnpm-lock.yaml is required")

    template = _template_values(ROOT / ".env.production.example")
    for key, expected in EXPECTED_PRODUCTION_TEMPLATE.items():
        if template.get(key) != expected:
            failures.append(f".env.production.example {key} must be {expected!r}")

    tracked = _tracked_paths()
    lockfiles = sorted(
        path for path in tracked if Path(path).name in FORBIDDEN_LOCKFILES
    )
    if lockfiles:
        failures.append(
            f"tracked npm/yarn lockfiles are not allowed: {', '.join(lockfiles)}"
        )
    return failures


def main() -> int:
    try:
        failures = validate()
    except (RuntimeError, TypeError) as exc:
        print(f"Deployment configuration guard failed: {exc}")
        return 1
    if failures:
        print("Deployment configuration guard failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "Deployment configuration guard passed: two-project public settings are explicit."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
