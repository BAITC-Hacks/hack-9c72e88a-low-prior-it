"""Check OpenAI configuration; --live sends a synthetic forecast through both read-only tools."""

import argparse
import asyncio

from wind_agent.openai import OpenAIAnalyst
from wind_agent.orchestrator import ForecastAgent
from wind_agent.weather import DemoWeatherProvider
from wind_backend.config import Settings
from wind_backend.ml import DemoPowerCurve
from wind_contracts.models import ForecastRequest, Turbine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send synthetic summaries to OpenAI")
    args = parser.parse_args()
    config = Settings.from_env().openai
    print(config.status().model_dump_json(indent=2))
    if not args.live:
        return
    if not config.enabled or not config.api_key:
        parser.exit(
            2,
            "Set OPENAI_AGENT_ENABLED=true, OPENAI_API_KEY and NVIDIA_AGENT_ENABLED=false in .env.\n",
        )
    agent = ForecastAgent(DemoWeatherProvider(), DemoPowerCurve(), analyst=OpenAIAnalyst(config))
    result = asyncio.run(
        agent.run(
            ForecastRequest(turbine_ids=["turbine-1"], issued_at="2026-01-31T00:00:00Z"),
            [Turbine(id="turbine-1", name="Synthetic fixture")],
            lambda event: print(f"{event.stage}: {event.message}"),
        )
    )
    print(result.analysis.model_dump_json(indent=2))
    if result.analysis.status != "succeeded":
        parser.exit(1, "OpenAI smoke test failed; numerical demo forecast was retained.\n")


if __name__ == "__main__":
    main()
