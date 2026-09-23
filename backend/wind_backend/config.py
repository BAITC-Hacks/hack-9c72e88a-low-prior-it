import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from wind_agent.nvidia import NvidiaConfig
from wind_agent.openai import OpenAIConfig
from wind_contracts.models import Turbine


@dataclass(frozen=True)
class Settings:
    db_path: Path
    turbines_path: Path
    models_path: Path = Path("artifacts/models")
    nvidia: NvidiaConfig = field(default_factory=NvidiaConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)

    def __post_init__(self):
        if self.nvidia.enabled and self.openai.enabled:
            raise ValueError(
                "Enable only one cloud analyst: OPENAI_AGENT_ENABLED or NVIDIA_AGENT_ENABLED"
            )

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            db_path=Path(os.getenv("WINDFARM_DB", "data/windfarm.sqlite3")),
            turbines_path=Path(os.getenv("WINDFARM_TURBINES", "config/turbines.example.json")),
            models_path=Path(os.getenv("WINDFARM_MODELS", "artifacts/models")),
            nvidia=NvidiaConfig.from_env(),
            openai=OpenAIConfig.from_env(),
        )

    def turbines(self) -> list[Turbine]:
        values = json.loads(self.turbines_path.read_text(encoding="utf-8"))
        turbines = [Turbine.model_validate(value) for value in values]
        if not turbines or len({t.id for t in turbines}) != len(turbines):
            raise ValueError("Configure at least one turbine with unique IDs")
        return turbines
