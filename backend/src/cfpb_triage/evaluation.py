from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from cfpb_triage.paths import ARTIFACT_DIR, DUCKDB_PATH

SUMMARY_EVAL_SAMPLE_PATH = ARTIFACT_DIR / "summary_factuality_sample.json"
SUMMARY_EVAL_RUBRIC_VERSION = "summary-factuality-v1"
SUMMARY_EVAL_SEED = 42
SUMMARY_EVAL_STRATA = ("month", "product")


def _rank(seed: int, complaint_id: str) -> str:
    return hashlib.sha256(f"{seed}|{complaint_id}".encode()).hexdigest()


def freeze_summary_factuality_sample(
    *,
    database_path: Path = DUCKDB_PATH,
    output_path: Path = SUMMARY_EVAL_SAMPLE_PATH,
    sample_size: int = 50,
    seed: int = SUMMARY_EVAL_SEED,
) -> dict[str, Any]:
    """Freeze an ID-only round-robin sample stratified by month and product."""

    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT complaint_id, strftime(date_received, '%Y-%m') AS month, product
            FROM complaints
            WHERE has_narrative IS TRUE AND narrative IS NOT NULL
            ORDER BY complaint_id
            """
        ).fetchall()
        lineage_rows = connection.execute(
            "SELECT key, value FROM lineage_metadata"
        ).fetchall()
    finally:
        connection.close()
    lineage = dict(lineage_rows)
    strata: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for complaint_id, month, product in rows:
        strata[(month, product)].append((complaint_id, month, product))
    queues: list[tuple[tuple[str, str], deque[tuple[str, str, str]]]] = []
    for key in sorted(strata):
        ranked = sorted(strata[key], key=lambda item: _rank(seed, item[0]))
        queues.append((key, deque(ranked)))

    selected: list[dict[str, str]] = []
    while queues and len(selected) < min(sample_size, len(rows)):
        remaining = []
        for key, queue in queues:
            if queue and len(selected) < sample_size:
                complaint_id, month, product = queue.popleft()
                selected.append(
                    {
                        "complaint_id": complaint_id,
                        "month": month,
                        "product": product,
                    }
                )
            if queue:
                remaining.append((key, queue))
        queues = remaining

    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_unreviewed",
        "rubric_version": SUMMARY_EVAL_RUBRIC_VERSION,
        "sample_selection": {
            "method": "deterministic_hash_rank_round_robin_by_stratum",
            "seed": seed,
            "strata": list(SUMMARY_EVAL_STRATA),
            "eligible_population": len(rows),
            "requested_sample_size": sample_size,
            "selected_sample_size": len(selected),
        },
        "parent_snapshot_sha256": lineage.get("snapshot_sha256"),
        "items": selected,
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    payload["sample_manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload
