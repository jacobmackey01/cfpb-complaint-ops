from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn

from cfpb_triage.data.quality import run_quality_checks
from cfpb_triage.data.snapshot import download_recent_snapshot
from cfpb_triage.data.source_metrics import ingest_source_window_metrics
from cfpb_triage.data.warehouse import build_warehouse
from cfpb_triage.evaluation import (
    SUMMARY_EVAL_SAMPLE_PATH,
    SUMMARY_REVIEW_TEMPLATE_PATH,
    export_summary_review_template,
    import_summary_review,
    freeze_summary_factuality_sample,
)
from cfpb_triage.modeling.anomalies import generate_anomaly_report
from cfpb_triage.modeling.router import (
    apply_router_to_warehouse,
    load_training_rows,
    train_router,
)
from cfpb_triage.paths import (
    DUCKDB_PATH,
    MANIFEST_PATH,
    SNAPSHOT_PATH,
)
from cfpb_triage.services.demo import DEMO_NOTICE, synthetic_cases


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected ISO date YYYY-MM-DD") from exc


def _max_records(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 100_000:
        raise argparse.ArgumentTypeError("max-records must be between 1 and 100000")
    return parsed


def _manifest() -> dict[str, Any]:
    return (
        json.loads(MANIFEST_PATH.read_text("utf-8")) if MANIFEST_PATH.exists() else {}
    )


def _effective_as_of(value: date | None) -> date:
    if value:
        return value
    manifest_as_of = _manifest().get("as_of_date")
    return (
        date.fromisoformat(manifest_as_of)
        if manifest_as_of
        else datetime.now(timezone.utc).date()
    )


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def cmd_snapshot(args: argparse.Namespace) -> int:
    manifest = download_recent_snapshot(
        as_of=args.as_of,
        max_records=args.max_records,
        complete_months=args.complete_months,
        snapshot_path=args.output,
        manifest_path=args.manifest,
    )
    _print(manifest)
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    report = run_quality_checks(
        args.path,
        as_of=args.as_of,
        manifest_path=args.manifest if args.manifest.exists() else None,
    )
    _print(report.model_dump(mode="json"))
    return 0 if report.passed else 2


def cmd_warehouse(args: argparse.Namespace) -> int:
    result = build_warehouse(args.path, database_path=args.database)
    if args.manifest.exists():
        result["source_windows_ingested"] = ingest_source_window_metrics(
            database_path=args.database, manifest_path=args.manifest
        )
    _print(result)
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    as_of = _effective_as_of(args.as_of)
    manifest = _manifest()
    rows = load_training_rows(args.database)
    report = train_router(
        rows,
        as_of=as_of,
        snapshot_sha256=str(manifest.get("snapshot_sha256", "unknown")),
    )
    scoring = apply_router_to_warehouse(database_path=args.database)
    _print({"training": report, "warehouse_scoring": scoring})
    return 0


def cmd_anomalies(args: argparse.Namespace) -> int:
    report = generate_anomaly_report(
        database_path=args.database,
        as_of=_effective_as_of(args.as_of),
    )
    _print(report)
    return 0


def cmd_build_all(args: argparse.Namespace) -> int:
    manifest = download_recent_snapshot(
        as_of=args.as_of,
        max_records=args.max_records,
        complete_months=args.complete_months,
    )
    quality = run_quality_checks(
        SNAPSHOT_PATH, as_of=args.as_of, manifest_path=MANIFEST_PATH
    )
    if not quality.passed:
        _print(
            {
                "status": "stopped_on_quality_failure",
                "quality": quality.model_dump(mode="json"),
            }
        )
        return 2
    warehouse = build_warehouse(SNAPSHOT_PATH, database_path=DUCKDB_PATH)
    source_windows = ingest_source_window_metrics(
        database_path=DUCKDB_PATH,
        manifest_path=MANIFEST_PATH,
    )
    rows = load_training_rows(DUCKDB_PATH)
    model = train_router(
        rows,
        as_of=args.as_of,
        snapshot_sha256=manifest["snapshot_sha256"],
    )
    scoring = apply_router_to_warehouse(database_path=DUCKDB_PATH)
    anomalies = generate_anomaly_report(database_path=DUCKDB_PATH, as_of=args.as_of)
    _print(
        {
            "status": "complete",
            "snapshot": manifest,
            "quality_passed": quality.passed,
            "warehouse": warehouse,
            "source_windows_ingested": source_windows,
            "model": model,
            "scoring": scoring,
            "anomaly_count": len(anomalies["items"]),
        }
    )
    return 0


def cmd_freeze_summary_eval(args: argparse.Namespace) -> int:
    _print(
        freeze_summary_factuality_sample(
            database_path=args.database,
            sample_size=args.sample_size,
            seed=args.seed,
        )
    )
    return 0


def cmd_export_summary_review(args: argparse.Namespace) -> int:
    _print(
        export_summary_review_template(
            sample_path=args.sample,
            output_path=args.output,
        )
    )
    return 0


def cmd_import_summary_review(args: argparse.Namespace) -> int:
    _print(
        import_summary_review(
            sample_path=args.sample,
            worksheet_path=args.worksheet,
            database_path=args.database,
        )
    )
    return 0


def cmd_bootstrap_demo(_: argparse.Namespace) -> int:
    cases = synthetic_cases()
    _print(
        {
            "status": "ready",
            "source_kind": "synthetic_offline_demo",
            "case_count": len(cases),
            "writes_performed": False,
            "notice": DEMO_NOTICE,
        }
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    uvicorn.run(
        "cfpb_triage.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cfpb-triage",
        description="Reproducible CFPB complaint-operations pipeline and API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser(
        "snapshot", help="download a monthly-capped CFPB snapshot"
    )
    snapshot.add_argument("--as-of", type=_date, required=True)
    snapshot.add_argument(
        "--max-records",
        type=_max_records,
        default=os.getenv("CFPB_SNAPSHOT_LIMIT", "100000"),
    )
    snapshot.add_argument("--complete-months", type=int, default=12)
    snapshot.add_argument("--output", type=Path, default=SNAPSHOT_PATH)
    snapshot.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    snapshot.set_defaults(handler=cmd_snapshot)

    qa = subparsers.add_parser("qa", aliases=["quality"], help="validate a snapshot")
    qa.add_argument("path", type=Path, nargs="?", default=SNAPSHOT_PATH)
    qa.add_argument("--as-of", type=_date, default=datetime.now(timezone.utc).date())
    qa.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    qa.set_defaults(handler=cmd_qa)

    warehouse = subparsers.add_parser("warehouse", help="materialize the DuckDB model")
    warehouse.add_argument("path", type=Path, nargs="?", default=SNAPSHOT_PATH)
    warehouse.add_argument("--database", type=Path, default=DUCKDB_PATH)
    warehouse.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    warehouse.set_defaults(handler=cmd_warehouse)

    train = subparsers.add_parser(
        "train", help="train, calibrate, evaluate, and score the router"
    )
    train.add_argument("--as-of", type=_date)
    train.add_argument("--database", type=Path, default=DUCKDB_PATH)
    train.set_defaults(handler=cmd_train)

    anomalies = subparsers.add_parser(
        "anomalies", help="detect product and issue volume signals"
    )
    anomalies.add_argument("--as-of", type=_date)
    anomalies.add_argument("--database", type=Path, default=DUCKDB_PATH)
    anomalies.set_defaults(handler=cmd_anomalies)

    build_all = subparsers.add_parser(
        "build-all",
        aliases=["bootstrap"],
        help="run snapshot, QA, DuckDB, router, and anomaly stages",
    )
    build_all.add_argument("--as-of", type=_date, required=True)
    build_all.add_argument(
        "--max-records",
        type=_max_records,
        default=os.getenv("CFPB_SNAPSHOT_LIMIT", "100000"),
    )
    build_all.add_argument("--complete-months", type=int, default=12)
    build_all.set_defaults(handler=cmd_build_all)

    summary_eval = subparsers.add_parser(
        "freeze-summary-eval",
        help="freeze an ID-only sample for manual summary factuality review",
    )
    summary_eval.add_argument("--sample-size", type=int, default=50)
    summary_eval.add_argument("--seed", type=int, default=42)
    summary_eval.add_argument("--database", type=Path, default=DUCKDB_PATH)
    summary_eval.set_defaults(handler=cmd_freeze_summary_eval)

    summary_review = subparsers.add_parser(
        "export-summary-review",
        help="export a blank ID-only worksheet for private manual summary review",
    )
    summary_review.add_argument(
        "--sample",
        type=Path,
        default=SUMMARY_EVAL_SAMPLE_PATH,
    )
    summary_review.add_argument(
        "--output", type=Path, default=SUMMARY_REVIEW_TEMPLATE_PATH
    )
    summary_review.set_defaults(handler=cmd_export_summary_review)

    summary_review_import = subparsers.add_parser(
        "import-summary-review",
        help="validate and import completed private summary review rows",
    )
    summary_review_import.add_argument(
        "--sample",
        type=Path,
        default=SUMMARY_EVAL_SAMPLE_PATH,
    )
    summary_review_import.add_argument(
        "--worksheet",
        type=Path,
        default=SUMMARY_REVIEW_TEMPLATE_PATH,
    )
    summary_review_import.add_argument(
        "--database", type=Path, default=DUCKDB_PATH
    )
    summary_review_import.set_defaults(handler=cmd_import_summary_review)

    demo = subparsers.add_parser(
        "bootstrap-demo",
        help="validate the clearly labeled in-memory synthetic offline demo",
    )
    demo.set_defaults(handler=cmd_bootstrap_demo)

    serve = subparsers.add_parser("serve", help="run the FastAPI service")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(handler=cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
