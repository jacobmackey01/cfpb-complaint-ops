from __future__ import annotations

import json
from datetime import date

from cfpb_triage.data.quality import run_quality_checks


def test_quality_fails_closed_on_manifest_hash_or_source_health(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text(
        json.dumps(
            {
                "complaint_id": "1",
                "date_received": "2026-01-02",
                "date_sent_to_company": "2026-01-01",
                "product": "Mortgage",
                "issue": "Payment issue",
                "company": "Example",
                "state": "NY",
                "submitted_via": "Web",
                "company_response": "Closed with explanation",
                "timely": True,
                "narrative": "A sufficiently detailed complaint narrative for testing.",
                "has_narrative": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "snapshot_sha256": "0" * 64,
                "windows": [
                    {
                        "source_meta": {
                            "is_data_stale": True,
                            "has_data_issue": True,
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = run_quality_checks(
        snapshot,
        output_path=None,
        manifest_path=manifest,
        as_of=date(2026, 1, 31),
    )
    checks = {check.name: check for check in report.checks}
    assert checks["manifest_snapshot_sha256_matches"].passed is False
    assert checks["source_reports_no_data_issue"].passed is False
    assert checks["source_reports_fresh"].passed is False
    assert checks["date_sent_not_before_received"].passed is False
    assert report.passed is False
