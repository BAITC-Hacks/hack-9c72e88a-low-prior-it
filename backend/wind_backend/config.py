import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from wind_contracts.models import Turbine


@dataclass(frozen=True)
class Settings:
    db_path: Path
    turbines_path: Path

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            db_path=Path(os.getenv("WINDFARM_DB", "data/windfarm.sqlite3")),
            turbines_path=Path(os.getenv("WINDFARM_TURBINES", "config/turbines.example.json")),
        )

    def turbines(self) -> list[Turbine]:
        values = json.loads(self.turbines_path.read_text(encoding="utf-8"))
        turbines = [Turbine.model_validate(value) for value in values]
        if not turbines or len({t.id for t in turbines}) != len(turbines):
            raise ValueError("Configure at least one turbine with unique IDs")
        return turbines
