"""Optional NVIDIA NIM analyst using the shared forecast analysis tools."""

import json
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from wind_contracts.models import AgentAnalysis, AgentEvent, AgentStatus

from wind_agent.analysis import SYSTEM_PROMPT, TOOLS, CloudAnalyst

ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"


@dataclass(frozen=True)
class NvidiaConfig:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 30

    def __post_init__(self):
        if not self.model.strip() or len(self.model) > 200:
            raise ValueError("NVIDIA_MODEL must be a nonempty model ID (up to 200 characters)")
        if not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 120:
            raise ValueError("NVIDIA_TIMEOUT_SECONDS must be between 1 and 120")

    @classmethod
    def from_env(cls):
        flag = os.getenv("NVIDIA_AGENT_ENABLED", "false").strip().lower()
        if flag not in {"true", "false", "1", "0"}:
            raise ValueError("NVIDIA_AGENT_ENABLED must be true or false")
        return cls(
            enabled=flag in {"true", "1"},
            api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
            model=os.getenv("NVIDIA_MODEL", DEFAULT_MODEL).strip(),
            timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "30")),
        )

    def status(self):
        return AgentStatus(enabled=self.enabled, configured=bool(self.api_key), model=self.model)


class NvidiaAnalyst(CloudAnalyst):
    async def _run(self, client, outputs, used, emit):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Inspect this completed forecast using both tools, then summarize it.",
            },
        ]
        seen_ids = set()
        # At most two tool-selection requests plus one final report; no unbounded agent loop.
        for _ in range(3):
            remaining = [name for name in TOOLS if name not in used]
            payload = dict(
                model=self.config.model,
                messages=messages,
                stream=False,
                temperature=1.0,
                top_p=0.95,
                max_tokens=1024,
                chat_template_kwargs={"enable_thinking": False},
            )
            if remaining:
                payload["tools"] = [
                    dict(
                        type="function",
                        function=dict(
                            name=name,
                            description=TOOLS[name],
                            parameters=dict(
                                type="object",
                                properties={},
                                required=[],
                                additionalProperties=False,
                            ),
                        ),
                    )
                    for name in remaining
                ]
                payload["tool_choice"] = "required"
            response = await client.post(
                ENDPOINT, json=payload, headers={"Authorization": f"Bearer {self.config.api_key}"}
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError("Invalid assistant message")
            calls = message.get("tool_calls")
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                raise ValueError("Invalid tool calls")
            if calls:
                if choice.get("finish_reason") != "tool_calls":
                    raise ValueError("Incomplete tool response")
                if not 1 <= len(calls) <= len(remaining):
                    raise ValueError("Invalid tool call count")
                clean_calls = []
                batch_names = set()
                for call in calls:
                    name = call["function"]["name"]
                    identifier = call["id"]
                    if (
                        call.get("type") != "function"
                        or name not in remaining
                        or name in batch_names
                        or not isinstance(identifier, str)
                        or not 1 <= len(identifier) <= 200
                        or identifier in seen_ids
                        or json.loads(call["function"]["arguments"]) != {}
                    ):
                        raise ValueError("Unsupported tool call")
                    seen_ids.add(identifier)
                    batch_names.add(name)
                    clean_calls.append(
                        dict(
                            id=identifier, type="function", function=dict(name=name, arguments="{}")
                        )
                    )
                messages.append(dict(role="assistant", content=None, tool_calls=clean_calls))
                for call in clean_calls:
                    name = call["function"]["name"]
                    used.append(name)
                    emit(
                        AgentEvent(
                            at=datetime.now(UTC), stage="analyse", message=f"NVIDIA tool: {name}"
                        )
                    )
                    messages.append(
                        dict(
                            role="tool",
                            tool_call_id=call["id"],
                            content=json.dumps(outputs[name], allow_nan=False),
                        )
                    )
                continue
            content = message.get("content")
            if (
                remaining
                or choice.get("finish_reason") != "stop"
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError("Report requires both tools and a complete answer")
            summary = content.strip().replace(self.config.api_key, "[redacted]")[:4000]
            return AgentAnalysis(
                model=self.config.model, status="succeeded", summary=summary, tools_used=used.copy()
            )
        raise ValueError("Tool budget exhausted")
