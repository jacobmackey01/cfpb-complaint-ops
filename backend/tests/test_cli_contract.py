from __future__ import annotations

import pytest
from cfpb_triage.cli import build_parser


@pytest.mark.parametrize("command", ["snapshot", "build-all"])
def test_reproducible_extraction_requires_explicit_as_of(command: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([command])


@pytest.mark.parametrize("command", ["snapshot", "build-all"])
def test_snapshot_limit_cannot_exceed_public_contract(command: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [command, "--as-of", "2026-08-21", "--max-records", "100001"]
        )


def test_summary_review_export_command_is_available() -> None:
    args = build_parser().parse_args(["export-summary-review"])
    assert args.command == "export-summary-review"
    assert args.output.name == "summary_factuality_review_template.csv"
