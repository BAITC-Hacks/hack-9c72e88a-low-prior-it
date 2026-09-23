"""OpenAI Responses API adapter for bounded, read-only forecast analysis."""

import json
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from wind_contracts.models import AgentAnalysis, AgentEvent, AgentStatus

from wind_agent.analysis import SYSTEM_PROMPT, TOOLS, CloudAnalyst

ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class OpenAIConfig:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 30

    def __post_init__(self):
        if not self.model.strip() or len(self.model) > 200:
            raise ValueError("OPENAI_MODEL must be a nonempty model ID (up to 200 characters)")
        if not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 120:
            raise ValueError("OPENAI_TIMEOUT_SECONDS must be between 1 and 120")

    @classmethod
    def from_env(cls):
        flag = os.getenv("OPENAI_AGENT_ENABLED", "false").strip().lower()
        if flag not in {"true", "false", "1", "0"}:
            raise ValueError("OPENAI_AGENT_ENABLED must be true or false")
        return cls(
            enabled=flag in {"true", "1"},
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip(),
            timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
        )

    def status(self):
        return AgentStatus(
            provider="openai", enabled=self.enabled, configured=bool(self.api_key), model=self.model
        )


class OpenAIAnalyst(CloudAnalyst):
    provider = "openai"
    label = "OpenAI"

    async def _run(self, client, outputs, used, emit):
        history = [
            {
                "role": "user",
                "content": "Inspect this completed forecast using both tools, then summarize it.",
            }
        ]
        seen_ids = set()
        for _ in range(3):
            remaining = [name for name in TOOLS if name not in used]
            payload = dict(
                model=self.config.model,
                instructions=SYSTEM_PROMPT,
                input=history,
                store=False,
                max_output_tokens=1024,
            )
            if remaining:
                payload["tools"] = [
                    dict(
                        type="function",
                        name=name,
                        description=TOOLS[name],
                        strict=True,
                        parameters=dict(
                            type="object", properties={}, required=[], additionalProperties=False
                        ),
                    )
                    for name in remaining
                ]
                payload["tool_choice"] = "required"
            response = await client.post(
                ENDPOINT, json=payload, headers={"Authorization": f"Bearer {self.config.api_key}"}
            )
            response.raise_for_status()
            body = response.json()
            if body["status"] != "completed":
                raise ValueError("Incomplete response")
            items = body["output"]
            if (
                not isinstance(items, list)
                or not items
                or any(not isinstance(i, dict) for i in items)
            ):
                raise ValueError("Malformed output")
            if any(i.get("type") not in {"function_call", "message", "reasoning"} for i in items):
                raise ValueError("Unexpected output item")
            calls = [i for i in items if i.get("type") == "function_call"]
            if calls:
                if len(calls) > len(remaining):
                    raise ValueError("Tool budget exceeded")
                names = set()
                for call in calls:
                    name, identifier = call["name"], call["call_id"]
                    if (
                        name not in remaining
                        or name in names
                        or not isinstance(identifier, str)
                        or not 1 <= len(identifier) <= 200
                        or identifier in seen_ids
                        or json.loads(call["arguments"]) != {}
                    ):
                        raise ValueError("Unsupported tool call")
                    names.add(name)
                    seen_ids.add(identifier)
                # Responses continuation includes the original function calls before their outputs.
                history.extend(items)
                for call in calls:
                    name = call["name"]
                    used.append(name)
                    emit(
                        AgentEvent(
                            at=datetime.now(UTC), stage="analyse", message=f"OpenAI tool: {name}"
                        )
                    )
                    history.append(
                        dict(
                            type="function_call_output",
                            call_id=call["call_id"],
                            output=json.dumps(outputs[name], allow_nan=False),
                        )
                    )
                continue
            if remaining:
                raise ValueError("Both tools must be used before the report")
            parts = []
            for item in items:
                if item["type"] != "message":
                    continue
                if item.get("role") != "assistant" or item.get("status") != "completed":
                    raise ValueError("Incomplete assistant message")
                for part in item["content"]:
                    if (
                        not isinstance(part, dict)
                        or part.get("type") != "output_text"
                        or not isinstance(part.get("text"), str)
                    ):
                        raise ValueError("Refused or invalid report")
                    parts.append(part["text"])
            summary = "\n".join(parts).strip()
            if not summary:
                raise ValueError("Empty report")
            return AgentAnalysis(
                provider=self.provider,
                model=self.config.model,
                status="succeeded",
                summary=summary.replace(self.config.api_key, "[redacted]")[:4000],
                tools_used=used.copy(),
            )
        raise ValueError("Tool budget exhausted")
