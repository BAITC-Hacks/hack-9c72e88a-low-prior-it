import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from wind_agent.nvidia import ENDPOINT, NvidiaAnalyst, NvidiaConfig
from wind_agent.orchestrator import ForecastAgent
from wind_agent.weather import DemoWeatherProvider
from wind_backend.main import create_app
from wind_backend.ml import DemoPowerCurve
from wind_contracts.models import ForecastRequest, Turbine

from tests.conftest import ISSUE

KEY = "fake-test-key-not-a-credential"
REQUEST = ForecastRequest(turbine_ids=["turbine-1"], issued_at=ISSUE)
TURBINES = [Turbine(id="turbine-1", name="One")]


def response(content=None, calls=None, finish=None):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": finish or ("tool_calls" if calls else "stop"),
                    "message": {"role": "assistant", "content": content, "tool_calls": calls},
                }
            ]
        },
    )


def call(name, arguments="{}", identifier=None):
    return dict(
        id=identifier or name, type="function", function=dict(name=name, arguments=arguments)
    )


def forecast(analyst=None):
    events = []
    result = asyncio.run(
        ForecastAgent(DemoWeatherProvider(), DemoPowerCurve(), analyst=analyst).run(
            REQUEST, TURBINES, events.append
        )
    )
    return result, events


def analyst(handler):
    return NvidiaAnalyst(
        NvidiaConfig(enabled=True, api_key=KEY), transport=httpx.MockTransport(handler)
    )


def test_tools_then_advisory_report_preserve_every_prediction():
    sent = []

    def handler(request):
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        payload = json.loads(request.content)
        assert KEY not in json.dumps(payload)
        sent.append(payload)
        if len(sent) == 1:
            assert payload["tool_choice"] == "required"
            return response(
                calls=[call("forecast_summary"), call("quality_audit")], finish="tool_calls"
            )
        assert "tools" not in payload
        outputs = [json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"]
        assert len(outputs[0]["groups"]) == 2
        assert outputs[1]["is_demo_or_provisional"] is True
        assert outputs[1]["accuracy_measured_for_this_run"] is False
        return response("Synthetic forecast; verify archived weather before competition replay.")

    baseline, _ = forecast()
    result, events = forecast(analyst(handler))
    assert result.points == baseline.points
    assert [s.model_dump(exclude={"retrieved_at"}) for s in result.snapshots] == [
        s.model_dump(exclude={"retrieved_at"}) for s in baseline.snapshots
    ]
    assert result.input_fingerprint == baseline.input_fingerprint
    assert result.analysis.status == "succeeded"
    assert result.analysis.tools_used == ["forecast_summary", "quality_audit"]
    assert len(sent) == 2
    assert events[-1].stage == "complete"


def test_sequential_tools_are_bounded_to_three_requests():
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        if len(sent) < 3:
            name = ("forecast_summary", "quality_audit")[len(sent) - 1]
            assert name in [t["function"]["name"] for t in payload["tools"]]
            return response(calls=[call(name)], finish="tool_calls")
        return response("Provisional inputs limit this forecast.")

    result, _ = forecast(analyst(handler))
    assert result.analysis.status == "succeeded" and len(sent) == 3


@pytest.mark.parametrize(
    "reply",
    [
        response("Unsupported claim without tools."),
        response(calls=[call("overwrite_predictions")]),
        response(calls=[call("forecast_summary", '{"file":".env"}')]),
        response(calls=[call("forecast_summary"), call("forecast_summary", identifier="other")]),
        response(calls=[call("forecast_summary", "[]")]),
        response(calls=[call("forecast_summary")], finish="length"),
        response(calls=[call("forecast_summary")], finish="content_filter"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, text="not JSON"),
    ],
)
def test_malformed_or_unauthorized_actions_leave_forecast_unchanged(reply):
    baseline, _ = forecast()
    result, _ = forecast(analyst(lambda _: reply))
    assert result.points == baseline.points
    assert result.analysis.status == "unavailable"
    assert result.analysis.error_code == "invalid_response"
    assert result.analysis.tools_used == []


def test_malformed_final_tool_calls_are_not_accepted_as_a_report():
    replies = iter([
        response(calls=[call("forecast_summary"), call("quality_audit")], finish="tool_calls"),
        response("A malformed report must not be accepted.", calls={}),
    ])
    baseline, _ = forecast()
    result, _ = forecast(analyst(lambda _: next(replies)))
    assert result.points == baseline.points
    assert result.analysis.error_code == "invalid_response"
    assert not result.analysis.summary


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "authentication"),
        (403, "authentication"),
        (429, "rate_limit"),
        (500, "provider_error"),
        (302, "provider_error"),
    ],
)
def test_provider_failure_never_exposes_response_body_or_key(status, code):
    result, events = forecast(analyst(lambda _: httpx.Response(status, text=f"private {KEY}")))
    assert result.analysis.error_code == code
    assert len(result.points) == 48
    assert KEY not in result.model_dump_json() + str(events)


def test_missing_key_and_timeout_still_complete_forecast():
    result, _ = forecast(NvidiaAnalyst(NvidiaConfig(enabled=True)))
    assert result.analysis.error_code == "missing_api_key"

    def handler(request):
        raise httpx.ReadTimeout(f"never expose {KEY}", request=request)

    timed, _ = forecast(analyst(handler))
    assert timed.analysis.error_code == "timeout"
    assert timed.points == result.points
    assert KEY not in timed.model_dump_json()


def test_final_token_limit_is_not_published_as_complete_analysis():
    count = 0

    def handler(_):
        nonlocal count
        count += 1
        if count == 1:
            return response(calls=[call("forecast_summary"), call("quality_audit")])
        return response("truncated", finish="length")

    result, _ = forecast(analyst(handler))
    assert result.analysis.error_code == "invalid_response"
    assert result.analysis.summary == ""


def test_settings_and_status_do_not_expose_credentials(monkeypatch):
    monkeypatch.setenv("NVIDIA_AGENT_ENABLED", "true")
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    config = NvidiaConfig.from_env()
    assert config.enabled and config.status().configured
    assert KEY not in repr(config) + config.status().model_dump_json()
    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "nan")
    with pytest.raises(ValueError):
        NvidiaConfig.from_env()


def test_api_analysis_persists_and_replay_skips_cloud(settings, forecast_request, monkeypatch):
    enabled = replace(settings, nvidia=NvidiaConfig(enabled=True, api_key=KEY))
    calls = []

    def factory(config):
        def handler(request):
            calls.append(1)
            payload = json.loads(request.content)
            if "tools" in payload:
                return response(calls=[call("forecast_summary"), call("quality_audit")])
            return response("This is a synthetic integration fixture.")

        return NvidiaAnalyst(config, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("wind_backend.service.NvidiaAnalyst", factory)
    with TestClient(create_app(enabled)) as client:
        assert client.get("/api/v1/agent/status").json()["configured"] is True
        created = client.post("/api/v1/forecasts", json=forecast_request).json()
        run = client.get(f"/api/v1/forecasts/{created['id']}").json()
        assert run["status"] == "succeeded" and run["result"]["analysis"]["status"] == "succeeded"
        count = len(calls)
        backtest = client.post(
            "/api/v1/backtests",
            json=forecast_request
            | {
                "last_issued_at": ISSUE.isoformat(),
                "evaluation_start": "2026-02-01T00:00:00Z",
                "evaluation_end": "2026-02-02T00:00:00Z",
            },
        ).json()
        assert client.get(f"/api/v1/backtests/{backtest['id']}").json()["status"] == "succeeded"
        assert len(calls) == count
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/v1/forecasts/{created['id']}").json()["result"] == run["result"]
        assert restarted.get("/api/v1/agent/status").json()["enabled"] is False
