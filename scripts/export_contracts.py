"""Deterministic schema export. Does not start the database or a server."""
import json
from pathlib import Path

from wind_backend.main import create_app

root = Path(__file__).resolve().parents[1]
(root / "contracts/openapi.json").write_text(
    json.dumps(create_app().openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
