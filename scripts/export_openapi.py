import json
from pathlib import Path

from wind_backend.main import create_app

target = Path(__file__).resolve().parents[1] / "contracts" / "openapi.json"
target.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
print(f"Exported {target.name}")
