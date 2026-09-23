"""Check local NVIDIA configuration; --live runs a bounded synthetic tool-calling smoke test."""

import argparse
import asyncio

from wind_agent.nvidia import NvidiaAnalyst
from wind_agent.orchestrator import ForecastAgent
from wind_agent.weather import DemoWeatherProvider
from wind_backend.config import Settings
from wind_backend.ml import DemoPowerCurve
from wind_contracts.models import ForecastRequest, Turbine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send synthetic summaries to NVIDIA")
    args = parser.parse_args()
    config = Settings.from_env().nvidia
    print(config.status().model_dump_json(indent=2))
    if not args.live:
        return
    if not config.enabled or not config.api_key:
        parser.exit(
            2,
            "Set NVIDIA_AGENT_ENABLED=true, NVIDIA_API_KEY and OPENAI_AGENT_ENABLED=false in .env.\n",
        )
    request = ForecastRequest(turbine_ids=["turbine-1"], issued_at="2026-01-31T00:00:00Z")
    agent = ForecastAgent(DemoWeatherProvider(), DemoPowerCurve(), analyst=NvidiaAnalyst(config))
    result = asyncio.run(
        agent.run(
            request,
            [Turbine(id="turbine-1", name="Synthetic fixture")],
            lambda event: print(f"{event.stage}: {event.message}"),
        )
    )
    print(result.analysis.model_dump_json(indent=2))
    if result.analysis.status != "succeeded":
        parser.exit(1, "NVIDIA smoke test failed; numerical demo forecast was retained.\n")


if __name__ == "__main__":
    main()
