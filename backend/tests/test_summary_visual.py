from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts" / "public" / "summary_factuality_review_metrics.json"
SCRIPT = ROOT / "scripts" / "generate_summary_factuality_visual.py"


def _module():
    spec = importlib.util.spec_from_file_location("summary_visual", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_visual_is_deterministic_and_uses_committed_source_values(
    tmp_path: Path,
) -> None:
    module = _module()
    first = tmp_path / "first.svg"
    second = tmp_path / "second.svg"
    module.generate_visual(SOURCE, first)
    module.generate_visual(SOURCE, second)
    assert first.read_bytes() == second.read_bytes()
    svg = first.read_text(encoding="utf-8")
    for value in (
        'data-score="1" data-count="0"',
        'data-score="2" data-count="0"',
        'data-score="3" data-count="2"',
        'data-score="4" data-count="3"',
        'data-score="5" data-count="45"',
        "4.86/5",
        "100%",
        "90%",
        "n = 50",
        "2026-08-23",
    ):
        assert value in svg
    assert 'width="100%" height="auto" viewBox="0 0 1200 650"' in svg
    assert "complaint_id" not in svg
    assert "summary_id" not in svg


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("lineage_bound_review_count", 49, "lineage_bound_review_count"),
        ("mean_factuality_score", 4.5, "mean_factuality_score"),
    ],
)
def test_visual_validation_rejects_inconsistent_source(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    module = _module()
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload[field] = value
    source = tmp_path / "metrics.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        module.generate_visual(source, tmp_path / "invalid.svg")


def test_visual_validation_rejects_score_count_mismatch(tmp_path: Path) -> None:
    module = _module()
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload["score_distribution"]["5"] = 44
    source = tmp_path / "metrics.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="score counts"):
        module.generate_visual(source, tmp_path / "invalid.svg")
