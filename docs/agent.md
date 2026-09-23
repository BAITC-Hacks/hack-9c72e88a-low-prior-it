# Agent owner handoff

Branch: `Agent`. Primary entry point: `agent/wind_agent/orchestrator.py`.

The `analyse` stage now records descriptive mean/peak output and the largest adjacent-hour rises/drops for each turbine, with UTC timestamps and percentage-point units. Flat forecasts are identified explicitly. This analysis neither changes predictions nor adds probabilistic confidence or operational safety claims; demo/provisional status is included.

The watcher supports `--once` for a bounded refresh and `--once --fetch-run-init <UTC hour>` for a candidate-acquisition cycle. It downloads each selected turbine through the existing weather API, requires unverified provenance, then checks refresh eligibility. Failed acquisition stops before refresh and reports any partial candidates; JSON distinguishes unchanged/queued from completed forecasts. Downloading never grants historical verification. The normal polling mode still follows updated run IDs. See the [judge walkthrough](judges-walkthrough.md) for commands and remaining automation gaps.

## Public boundaries

```python
class WeatherProvider(Protocol):
    async def fetch(self, turbine: Turbine, request: ForecastRequest) -> WeatherSnapshot: ...


class Predictor(Protocol):
    info: ModelInfo

    def predict(
        self, turbine: Turbine, weather: list[WeatherPoint], issued_at: datetime
    ) -> list[ForecastPoint]: ...
```

The backend injects both implementations into `ForecastAgent`. The agent validates cutoffs and weather, calls the predictor, validates output coverage/bounds, emits structured `AgentEvent` records, and returns `ForecastResult`. Its input fingerprint excludes retrieval times and record IDs, and includes actual weather content, provenance, request, and model metadata.

`TransientWeatherError` permits up to three attempts. `WeatherUnavailable` is terminal: do not turn missing archives into observed weather. Both the archive adapter and orchestrator independently check availability. The archive adapter selects the newest eligible **complete** run; an incomplete newer run can be bypassed for an older complete one. Add an explicit decision event if you extend that fallback policy.

## Weather fields

- Source: `demo`, `open-meteo-single-run`, or `external-archive`.
- Provenance: model name, initialization time, retrieval time, actual publication time, evidence, verification status.
- Inputs: UTC valid timestamp, wind speed in m/s, direction in degrees, temperature in °C, and snapshot-level wind height.
- Initial adapter requests ECMWF at 100 m. Validate archive-specific model identifiers, available variables, native/interpolated temporal resolution, and coverage with real coordinates.

Downloaded candidates deliberately have `verification=unverified` and `available_at=null`. Verification is an explicit team data-review action, not an LLM guess. Create a new immutable snapshot revision after collecting evidence. Do not equate `generationtime_ms` (API request processing time) with forecast publication.

## To build next

1. Real coordinates and archived-run audit for the competition period.
2. Preserve raw provider payloads + checksums + query parameters alongside normalized snapshots.
3. Station-specific hub-height conversion/bias correction agreed with the ML owner.
4. Automatic new-run detection, verified ingestion, and a scheduler that advances issue time.
5. Better diagnostics for missing, stale, or inconsistent weather; bounded repair/fallback policies.
6. Optional LLM planning/reporting using these tools; retain deterministic enforcement of all temporal rules.

The watcher only refreshes an existing issue time when stored input content changes. It never rewrites previous forecasts. Retraining produces a new model ID; submit a new forecast to use it.

## Acceptance

```sh
uv run pytest tests/test_leakage.py tests/test_weather_adapter.py
```

Add offline fixtures for verified provider runs. Include tests for future publication, incomplete horizons, unavailable archive dates, wrong units, duplicate hours, retry exhaustion, and input revisions. The external adapter is mocked in the starter tests; no live archive success is claimed.
