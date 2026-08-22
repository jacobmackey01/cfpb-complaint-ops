"""ASGI entry point used by local runners and deployment platforms."""

from pathlib import Path
import sys


_BACKEND_SRC = Path(__file__).resolve().parent / "backend" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

from cfpb_triage.api import app

__all__ = ["app"]
