# OpenAI forecast analyst

OpenAI is an alternative cloud provider when NVIDIA NIM access is unavailable.
The integration uses the [Responses API with function calling](https://developers.openai.com/api/docs/guides/function-calling)
and defaults to [gpt-4.1-mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
This model supports the short tool-based reporting workflow; it is not a claim
that it is OpenAI's newest model. The existing locked `httpx` dependency handles
requests, so no additional SDK or GPU installation is needed.

## Enable

Create a project API key through the [OpenAI API platform](https://platform.openai.com/api-keys).
Check account access and API billing; calls are charged according to
[API pricing](https://developers.openai.com/api/docs/pricing). A supported country
does not by itself guarantee project quota or access to every model. Kazakhstan
is listed in the [supported countries](https://developers.openai.com/api/docs/supported-countries).

Add these values to the repository-root `.env`:

```dotenv
NVIDIA_AGENT_ENABLED=false
OPENAI_AGENT_ENABLED=true
OPENAI_API_KEY=your-project-key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=30
```

Keys stay in this ignored backend file, never in `VITE_` variables, source code,
requests from the browser, or chat. Only one analyst may be enabled; enabling both
providers fails configuration validation. There is no automatic cross-provider fallback.

```powershell
.\.venv\Scripts\python.exe scripts/check_openai.py
.\.venv\Scripts\python.exe scripts/check_openai.py --live
```

The first command checks configuration without network access or printing the key.
`--live` makes up to three API requests using synthetic forecast summaries and exits
nonzero on error. It does not train CatBoost or alter the registry. Passing offline
tests does not establish live API access; verify with your own key.

Restart the backend after editing `.env`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn wind_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Check `GET /api/v1/agent/status` in Swagger at `http://127.0.0.1:8000/docs`.
With OpenAI enabled, it reports `provider=openai`, enabled/configured flags and
model ID, never credentials. `configured=true` means a key is present, not that
the API has authenticated it. Create a new forecast; the dashboard displays the
report under **Autonomous agent → OpenAI analysis**.

## Scope and failure behavior

The existing forecasting agent acquires and validates weather, calculates power,
then invokes the optional analyst. Shared tools in `agent/wind_agent/analysis.py`
expose only computed forecast aggregates and a deterministic quality/provenance
audit. Both tools must be used before the report. They have no arguments, file
access, model training, archive verification or forecast mutation capabilities.

The Responses conversation passes function calls and their `function_call_output`
records back to the model. Requests use `store=false` with local continuation
history; this setting is not a claim of zero provider retention. The integration
has at most three API calls, two tool executions, 1,024 output tokens per call and
a total timeout of 30 seconds (configurable 1–120). Only the default model has been
covered by this integration's protocol fixtures; other model IDs need a live check.

The summary is advisory English text. Numerical power points, source verification,
demo labels and fingerprints are computed independently and remain unchanged.
Bad credentials, missing keys, quota/rate-limit errors, malformed output, refused
or truncated answers, unsupported tools and timeouts yield `analysis.status=unavailable`
while retaining the successful forecast. Raw error bodies and keys are not persisted.
Backtests skip cloud analysis entirely. Changing analyst settings does not retrigger
an unchanged-input refresh; create a new forecast for a new report.

CatBoost weights and its matching dataset/registry remain separate local artifacts.
An OpenAI key does not populate the numerical model selector in a fresh clone;
follow [training reproduction](ml-training.md) for that.

## Verification

`tests/test_openai.py` covers parallel/sequential tool calls, complete Responses
history, no server-side response storage request, unchanged predictions/fingerprint,
strict tool admission, malformed output, refusals, deadlines, credentials, provider
selection, saved reports after restart, and omission during backtests. NVIDIA's
offline tests remain in place to protect the alternate adapter.
