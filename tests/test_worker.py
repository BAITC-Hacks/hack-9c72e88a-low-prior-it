import json
from datetime import timedelta

import httpx
import pytest
from wind_agent import worker
from wind_backend import routes
from wind_contracts.models import ForecastRequest, ForecastResult, ForecastRun

from .conftest import ISSUE, snapshot


def forecast(identifier="run-original", status="succeeded"):
    return ForecastRun(
        id=identifier,
        created_at=ISSUE,
        status=status,
        request=ForecastRequest(
            turbine_ids=["turbine-1", "turbine-2"], issued_at=ISSUE, weather_source="archive"
        ),
        result=ForecastResult(
            model_id="demo-power-curve",
            input_fingerprint="original",
            is_demo=True,
            snapshots=[],
            points=[],
            warnings=[],
        )
        if status == "succeeded"
        else None,
    ).model_dump(mode="json")


def candidate(turbine_id="turbine-1", **updates):
    return snapshot(
        f"candidate-{turbine_id}",
        **{
            "turbine_id": turbine_id,
            "source": "open-meteo-single-run",
            "weather_model": "ecmwf_ifs",
            "run_init": ISSUE,
            "verification": "unverified",
            "available_at": None,
            "availability_evidence": None,
        }
        | updates,
    )


def test_candidate_cycle_downloads_each_turbine_before_refresh_without_verifying():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=forecast())
        if request.url.path == "/api/v1/weather/fetch":
            payload = json.loads(request.content)
            assert payload["run_init"] == "2026-01-31T00:00:00Z"
            assert payload["weather_model"] == "ecmwf_ifs"
            assert set(payload) == {"turbine_id", "run_init", "weather_model"}
            return httpx.Response(
                201, json=candidate(payload["turbine_id"]).model_dump(mode="json")
            )
        return httpx.Response(200, json={"changed": False, "run": forecast()})

    with httpx.Client(
        base_url="http://worker.test", transport=httpx.MockTransport(handler)
    ) as client:
        report = worker.run_cycle(client, "run-original", fetch_run_init=ISSUE)

    assert calls == [
        ("GET", "/api/v1/forecasts/run-original"),
        ("POST", "/api/v1/weather/fetch"),
        ("POST", "/api/v1/weather/fetch"),
        ("POST", "/api/v1/forecasts/run-original/refresh"),
    ]
    assert report["cycle_status"] == "completed"
    assert report["refresh"]["changed"] is False
    assert [row["id"] for row in report["candidates"]] == [
        "candidate-turbine-1",
        "candidate-turbine-2",
    ]
    assert all(
        row["verification"] == "unverified" and row["available_at"] is None
        for row in report["candidates"]
    )
    assert all(row["accepted_as_unverified_candidate"] for row in report["candidates"])
    assert "no publication time was inferred" in report["acquisition_note"]


@pytest.mark.parametrize(
    "updates",
    [
        {
            "verification": "verified",
            "available_at": ISSUE,
            "availability_evidence": "Unexpected provider claim",
        },
        {"available_at": ISSUE},
        {"turbine_id": "wrong-turbine"},
    ],
)
def test_candidate_cycle_rejects_unexpected_provenance_or_turbine(updates):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=forecast())
        return httpx.Response(201, json=candidate(**updates).model_dump(mode="json"))

    with httpx.Client(
        base_url="http://worker.test", transport=httpx.MockTransport(handler)
    ) as client:
        report = worker.run_cycle(client, "run-original", fetch_run_init=ISSUE)

    assert report["cycle_status"] == "failed"
    assert report["refresh"] is None
    assert report["error"]["stage"] == "fetch_weather"
    assert report["candidates"][0]["accepted_as_unverified_candidate"] is False
    assert calls == ["/api/v1/forecasts/run-original", "/api/v1/weather/fetch"]


def test_partial_download_failure_keeps_candidate_id_and_stops_before_refresh():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json=forecast())
        turbine_id = json.loads(request.content)["turbine_id"]
        if turbine_id == "turbine-2":
            return httpx.Response(503, json={"message": "Provider temporarily unavailable"})
        return httpx.Response(201, json=candidate(turbine_id).model_dump(mode="json"))

    with httpx.Client(
        base_url="http://worker.test", transport=httpx.MockTransport(handler)
    ) as client:
        report = worker.run_cycle(client, "run-original", fetch_run_init=ISSUE)

    assert report["cycle_status"] == "failed"
    assert report["refresh"] is None
    assert len(report["candidates"]) == 1
    assert report["candidates"][0]["id"] == "candidate-turbine-1"
    assert report["error"]["turbine_id"] == "turbine-2"
    assert "503" in report["error"]["message"]
    assert calls == [
        "/api/v1/forecasts/run-original",
        "/api/v1/weather/fetch",
        "/api/v1/weather/fetch",
    ]


def test_future_initialization_fails_before_any_download():
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=forecast())

    with httpx.Client(
        base_url="http://worker.test", transport=httpx.MockTransport(handler)
    ) as client:
        report = worker.run_cycle(client, "run-original", fetch_run_init=ISSUE + timedelta(hours=1))

    assert calls == ["GET"]
    assert report["cycle_status"] == "failed"
    assert "later than" in report["error"]["message"]


@pytest.mark.parametrize("status_code,expected_exit", [(200, 0), (409, 1)])
def test_once_has_deterministic_exit_and_reports_queued_forecast(
    monkeypatch, capsys, status_code, expected_exit
):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(
            status_code, json={"changed": True, "run": forecast("run-next", "queued")}
        )

    client = httpx.Client(base_url="http://worker.test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(worker.httpx, "Client", lambda **_: client)
    assert worker.main(["--run-id", "run-original", "--once"]) == expected_exit
    report = json.loads(capsys.readouterr().out)
    assert calls == ["/api/v1/forecasts/run-original/refresh"]
    if expected_exit == 0:
        assert report["cycle_status"] == "completed"
        assert report["refresh"]["forecast_status"] == "queued"
    else:
        assert report["cycle_status"] == "failed"
        assert report["error"]["stage"] == "refresh"


def test_default_watcher_keeps_polling_and_follows_new_run_without_downloads(monkeypatch, capsys):
    calls = []
    sleeps = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"changed": len(calls) == 1, "run": forecast("run-next")})

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    client = httpx.Client(base_url="http://worker.test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(worker.httpx, "Client", lambda **_: client)
    monkeypatch.setattr(worker.time, "sleep", sleep)
    assert worker.main(["--run-id", "run-original", "--interval", "5"]) == 0
    assert calls == [
        ("POST", "/api/v1/forecasts/run-original/refresh"),
        ("POST", "/api/v1/forecasts/run-next/refresh"),
    ]
    assert sleeps == [5, 5]
    assert "changed=True run=run-next" in capsys.readouterr().out


def test_failed_forecast_in_successful_http_response_is_not_a_successful_cycle():
    with httpx.Client(
        base_url="http://worker.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"changed": True, "run": forecast("run-next", "failed")}
            )
        ),
    ) as client:
        report = worker.run_cycle(client, "run-original")
    assert report["cycle_status"] == "failed"
    assert report["refresh"]["forecast_status"] == "failed"
    assert report["error"]["message"] == "Refreshed forecast failed"


def test_default_watcher_recovers_after_http_error(monkeypatch, capsys):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"changed": False, "run": forecast()})

    def sleep(_):
        if len(calls) == 2:
            raise KeyboardInterrupt

    client = httpx.Client(base_url="http://worker.test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(worker.httpx, "Client", lambda **_: client)
    monkeypatch.setattr(worker.time, "sleep", sleep)
    assert worker.main(["--run-id", "run-original"]) == 0
    assert calls == ["/api/v1/forecasts/run-original/refresh"] * 2
    output = capsys.readouterr().out
    assert "Refresh failed:" in output and "changed=False run=run-original" in output


@pytest.mark.parametrize(
    "moment",
    ["2026-01-31T00:00:00", "2026-01-31T00:00:00+06:00", "2026-01-31T00:30:00Z", "not-a-time"],
)
def test_fetch_argument_requires_explicit_utc_hour(moment):
    with pytest.raises(SystemExit) as exc:
        worker.main(["--run-id", "run-original", "--once", "--fetch-run-init", moment])
    assert exc.value.code == 2


def test_fetch_requires_once_and_accepts_explicit_zero_offset():
    assert worker.utc_hour("2026-01-31T00:00:00Z") == ISSUE
    assert worker.utc_hour("2026-01-31T00:00:00+00:00") == ISSUE
    with pytest.raises(SystemExit) as exc:
        worker.main(["--run-id", "run-original", "--fetch-run-init", "2026-01-31T00:00:00Z"])
    assert exc.value.code == 2


def test_real_api_keeps_downloaded_candidate_unverified_and_existing_forecast_unchanged(
    client, forecast_request, monkeypatch
):
    verified = snapshot()
    assert (
        client.post("/api/v1/weather/snapshots", json=verified.model_dump(mode="json")).status_code
        == 201
    )
    created = client.post(
        "/api/v1/forecasts",
        json=forecast_request | {"turbine_ids": ["turbine-1"], "weather_source": "archive"},
    ).json()
    original = client.get(f"/api/v1/forecasts/{created['id']}").json()
    assert original["status"] == "succeeded"

    async def download(turbine, run_init, weather_model):
        assert run_init == ISSUE and weather_model == "ecmwf_ifs"
        return candidate(turbine.id)

    monkeypatch.setattr(routes, "download_single_run", download)
    report = worker.run_cycle(client, created["id"], fetch_run_init=ISSUE)

    assert report["cycle_status"] == "completed"
    assert report["refresh"]["changed"] is False
    assert report["candidates"][0]["verification"] == "unverified"
    assert client.get(f"/api/v1/forecasts/{created['id']}").json() == original
    stored = {row["id"]: row for row in client.get("/api/v1/weather/snapshots").json()}
    assert stored["candidate-turbine-1"]["verification"] == "unverified"
    assert stored["candidate-turbine-1"]["available_at"] is None
    assert stored[verified.id]["verification"] == "verified"
