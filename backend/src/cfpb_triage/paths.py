from __future__ import annotations

import os
from pathlib import Path

# Defaults are private/runtime locations. Promotion into artifacts/public is a
# separate, explicit privacy-review step.
BACKEND_ROOT = Path(
    os.getenv("BACKEND_ROOT", str(Path(__file__).resolve().parents[3]))
).resolve()
DATA_DIR = Path(
    os.getenv("DATA_DIR", os.getenv("CFPB_DATA_DIR", str(BACKEND_ROOT / "data")))
).resolve()
ARTIFACT_DIR = Path(
    os.getenv(
        "ARTIFACT_DIR",
        os.getenv("CFPB_ARTIFACT_DIR", str(BACKEND_ROOT / "artifacts" / "runtime")),
    )
).resolve()
SNAPSHOT_DIR = DATA_DIR / "raw" / "cfpb"
SNAPSHOT_PATH = Path(
    os.getenv("CFPB_SNAPSHOT_PATH", str(SNAPSHOT_DIR / "complaints.jsonl"))
).resolve()
MANIFEST_PATH = Path(
    os.getenv("CFPB_MANIFEST_PATH", str(SNAPSHOT_DIR / "manifest.json"))
).resolve()
QUALITY_PATH = Path(
    os.getenv("CFPB_QUALITY_PATH", str(ARTIFACT_DIR / "quality_report.json"))
).resolve()
DUCKDB_PATH = Path(
    os.getenv(
        "DUCKDB_PATH",
        os.getenv("CFPB_DUCKDB_PATH", str(DATA_DIR / "local" / "complaints.duckdb")),
    )
).resolve()
MODEL_PATH = Path(
    os.getenv("CFPB_MODEL_PATH", str(ARTIFACT_DIR / "product_router.joblib"))
).resolve()
MODEL_METRICS_PATH = Path(
    os.getenv("CFPB_MODEL_METRICS_PATH", str(ARTIFACT_DIR / "model_metrics.json"))
).resolve()
ANOMALIES_PATH = Path(
    os.getenv("CFPB_ANOMALIES_PATH", str(ARTIFACT_DIR / "anomalies.json"))
).resolve()


def ensure_local_directories() -> None:
    """Create ignored runtime directories only when a command needs them."""

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
