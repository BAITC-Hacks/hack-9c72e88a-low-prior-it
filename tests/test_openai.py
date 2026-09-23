import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from wind_agent.nvidia import NvidiaConfig
from wind_agent.openai import ENDPOINT, OpenAIAnalyst, OpenAIConfig
from wind_backend.main import create_app

from tests.conftest import ISSUE
from tests.test_nvidia import forecast

KEY = "fake-openai-test-key"


def call(name, arguments="{}", identifier=None):
    return dict(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=identifier or name,
        id=f"fc_{identifier or name}",
        status="completed",
    )


def message(text="Provisional forecast. Verify the weather archive before replay."):
    return dict(
        type="message",
        id="msg_1",
        role="assistant",
        status="completed",
        content=[dict(type="output_text", text=text, annotations=[])],
    )


def response(items, status="completed"):
    return httpx.Response(200, json=dict(id="resp_fixture", status=status, output=items))


def analyst(handler):
    return OpenAIAnalyst(
        OpenAIConfig(enabled=True, api_key=KEY), transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize("sequential", [False, True])
def test_responses_tool_continuation_preserves_numeric_forecast(sequential):
    sent = []

    def handler(request):
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        payload = json.loads(request.content)
        assert payload["store"] is False and KEY not in json.dumps(payload)
        assert "chat_template_kwargs" not in payload
        sent.append(payload)
        if "tools" in payload:
            names = [t["name"] for t in payload["tools"]]
            assert all(t["strict"] for t in payload["tools"])
            return response([call(name) for name in (names[:1] if sequential else names)])
        outputs = [i for i in payload["input"] if i.get("type") == "function_call_output"]
        assert {i["call_id"] for i in outputs} == {"forecast_summary", "quality_audit"}
        assert len([i for i in payload["input"] if i.get("type") == "function_call"]) == 2
        audit = json.loads(next(i["output"] for i in outputs if i["call_id"] == "quality_audit"))
        assert audit["is_demo_or_provisional"] and not audit["accuracy_measured_for_this_run"]
        return response([message()])

    baseline, _ = forecast()
    result, events = forecast(analyst(handler))
    assert (
        result.points == baseline.points and result.input_fingerprint == baseline.input_fingerprint
    )
    assert result.analysis.provider == "openai" and result.analysis.status == "succeeded"
    assert set(result.analysis.tools_used) == {"forecast_summary", "quality_audit"}
    assert len(sent) == (3 if sequential else 2)
    assert any(e.message.startswith("OpenAI tool:") for e in events)
    assert any("hourly means" in e.message for e in events if e.stage == "analyse")


@pytest.mark.parametrize(
    "items",
    [
        [message()],
        [call("write_file")],
        [call("forecast_summary", '{"path":".env"}')],
        [call("forecast_summary") | {"status": "incomplete"}],
        [call("forecast_summary"), call("forecast_summary", identifier="other")],
        [dict(type="shell_call")],
        [],
        ["invalid"],
    ],
)
def test_invalid_or_unauthorized_tools_preserve_forecast(items):
    result, _ = forecast(analyst(lambda _: response(items)))
    assert result.analysis.error_code == "invalid_response"
    assert result.analysis.provider == "openai" and len(result.points) == 48


@pytest.mark.parametrize(
    "reply",
    [
        response([message()], status="incomplete"),
        response([message() | {"content": [{"type": "refusal", "refusal": "No"}]}]),
        response([message() | {"content": ["malformed"]}]),
        response([message("")]),
    ],
)
def test_incomplete_or_refused_final_answer_is_not_a_report(reply):
    calls = []

    def handler(_):
        calls.append(1)
        return (
            response([call("forecast_summary"), call("quality_audit")])
            if len(calls) == 1
            else reply
        )

    result, _ = forecast(analyst(handler))
    assert result.analysis.error_code == "invalid_response" and not result.analysis.summary


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "authentication"),
        (403, "authentication"),
        (429, "rate_limit"),
        (500, "provider_error"),
    ],
)
def test_http_errors_redact_credentials_and_keep_predictions(status, code):
    result, events = forecast(analyst(lambda _: httpx.Response(status, text=KEY)))
    assert result.analysis.error_code == code and result.analysis.provider == "openai"
    assert KEY not in result.model_dump_json() + str(events)
    assert len(result.points) == 48


def test_missing_key_and_overall_deadline():
    missing, _ = forecast(OpenAIAnalyst(OpenAIConfig(enabled=True)))
    assert missing.analysis.error_code == "missing_api_key"

    async def slow(_):
        await asyncio.sleep(10)
        return response([message()])

    result, _ = forecast(
        OpenAIAnalyst(
            OpenAIConfig(enabled=True, api_key=KEY, timeout_seconds=1),
            transport=httpx.MockTransport(slow),
        )
    )
    assert result.analysis.error_code == "timeout" and result.points == missing.points


def test_configuration_validates_and_never_displays_key(settings, monkeypatch):
    monkeypatch.setenv("OPENAI_AGENT_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    config = OpenAIConfig.from_env()
    assert config.status().provider == "openai" and config.status().configured
    assert KEY not in repr(config) + config.status().model_dump_json()
    with pytest.raises(ValueError, match="only one"):
        replace(settings, nvidia=NvidiaConfig(enabled=True), openai=config)
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "nan")
    with pytest.raises(ValueError):
        OpenAIConfig.from_env()


def test_api_uses_selected_provider_persists_report_and_skips_replay(
    settings, forecast_request, monkeypatch
):
    enabled = replace(settings, openai=OpenAIConfig(enabled=True, api_key=KEY))
    calls = []

    def factory(config):
        def handler(request):
            calls.append(1)
            payload = json.loads(request.content)
            return (
                response([call("forecast_summary"), call("quality_audit")])
                if "tools" in payload
                else response([message()])
            )

        return OpenAIAnalyst(config, transport=httpx.MockTransport(handler))

    def forbidden(*args, **kwargs):
        pytest.fail("NVIDIA must never be called when OpenAI is selected")

    monkeypatch.setattr("wind_backend.service.OpenAIAnalyst", factory)
    monkeypatch.setattr("wind_backend.service.NvidiaAnalyst", forbidden)
    with TestClient(create_app(enabled)) as client:
        assert client.get("/api/v1/agent/status").json()["provider"] == "openai"
        assert client.get("/api/v1/evidence").status_code == 200
        assert client.get("/api/v1/evidence/export").status_code == 200
        created = client.post("/api/v1/forecasts", json=forecast_request).json()
        run = client.get(f"/api/v1/forecasts/{created['id']}").json()
        assert run["status"] == "succeeded" and run["result"]["analysis"]["provider"] == "openai"
        assert len(calls) == 2
        replay = client.post(
            "/api/v1/backtests",
            json=forecast_request
            | {
                "last_issued_at": ISSUE.isoformat(),
                "evaluation_start": "2026-02-01T00:00:00Z",
                "evaluation_end": "2026-02-02T00:00:00Z",
            },
        ).json()
        assert client.get(f"/api/v1/backtests/{replay['id']}").json()["status"] == "succeeded"
        assert len(calls) == 2
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/v1/forecasts/{created['id']}").json()["result"] == run["result"]
