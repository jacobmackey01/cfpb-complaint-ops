from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

LINEAGE_SCHEMA_VERSION = "1.0.0"
TRACKED_PACKAGES = ("duckdb", "httpx", "numpy", "pydantic", "scikit-learn")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_request_plan(
    *, endpoint: str, windows: list[dict[str, Any]], page_size_max: int
) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "http_method": "GET",
        "response_format": "default_json",
        "pagination": {
            "offset_parameter": "frm",
            "page_size_parameter": "size",
            "page_size_max": page_size_max,
        },
        "fixed_parameters": {
            "sort": "created_date_desc",
            "no_aggs": "true",
            "no_highlight": "true",
        },
        "date_semantics": {
            "date_received_min": "inclusive",
            "date_received_max": "exclusive",
        },
        "windows": [
            {
                "name": item["name"],
                "date_received_min": item["date_received_min"],
                "date_received_max_exclusive": item["date_received_max_exclusive"],
                "selection_cap": item["selection_cap"],
            }
            for item in windows
        ],
    }


def _git_state(workspace_root: Path) -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return {"commit": revision, "dirty": bool(status.strip())}
    except (FileNotFoundError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def runtime_fingerprint(workspace_root: Path) -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for package in TRACKED_PACKAGES:
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    return {
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": packages,
        "git": _git_state(workspace_root),
    }


def enrich_snapshot_manifest(
    manifest: dict[str, Any],
    *,
    workspace_root: Path,
    endpoint: str,
    page_size_max: int,
) -> dict[str, Any]:
    enriched = dict(manifest)
    plan = canonical_request_plan(
        endpoint=endpoint,
        windows=list(enriched.get("windows", [])),
        page_size_max=page_size_max,
    )
    page_hashes = [
        page
        for window in enriched.get("windows", [])
        for page in window.get("page_response_hashes", [])
    ]
    enriched["lineage"] = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "canonical_request_plan": plan,
        "canonical_request_sha256": canonical_json_sha256(plan),
        "canonical_rowset_sha256": enriched.get("snapshot_sha256"),
        "runtime": runtime_fingerprint(workspace_root),
        "parent_artifacts": [],
        "page_response_hashes": page_hashes,
    }
    without_manifest_hash = dict(enriched)
    enriched["manifest_content_sha256"] = canonical_json_sha256(without_manifest_hash)
    return enriched
