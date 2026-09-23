# Optional NVIDIA cloud analyst

If regional/account access prevents NVIDIA API use, [OpenAI integration](openai-agent.md)
is also available. Enable exactly one provider; no fallback sends data to another
provider automatically.

The existing forecasting agent can use NVIDIA NIM for advisory analysis after
deterministic prediction and validation. CatBoost/ridge/persistence still calculate
every power value. NVIDIA is a separate language model and does not appear in the
Prediction model selector or replace the trained CatBoost files.

The integration uses the existing locked `httpx` dependency; no additional SDK,
CUDA installation or local GPU is needed for this cloud client. It calls NVIDIA's
documented [chat-completions endpoint](https://docs.api.nvidia.com/nim/re/reference/llm-apis).
The default is [NVIDIA Nemotron 3 Super](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/build),
configurable through `NVIDIA_MODEL`. API access depends on the developer account.

## Install and configure

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\uv.exe sync --locked --python .venv/Scripts/python.exe --cache-dir .uv-cache
npm.cmd ci
```

For a fresh clone with uv already installed, use `uv sync --locked` to create
`.venv`. The Python dependency source is `pyproject.toml` / `uv.lock`; frontend
dependencies are in the workspace manifests / `package-lock.json`.

Obtain an API key from the NVIDIA model's **Build** page. Add these settings to
the local `.env` (create it from `.env.example` only if it does not already exist):

```dotenv
OPENAI_AGENT_ENABLED=false
NVIDIA_AGENT_ENABLED=true
NVIDIA_API_KEY=your-key-here
NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b
NVIDIA_TIMEOUT_SECONDS=30
```

Keep the key on the backend in this ignored file. Do not use a `VITE_` variable or
paste credentials into an API request or chat. Restart the backend after changing
`.env`; file reload alone is not a reliable configuration refresh.

```powershell
.\.venv\Scripts\python.exe scripts/check_nvidia.py
.\.venv\Scripts\python.exe scripts/check_nvidia.py --live
.\.venv\Scripts\python.exe -m uvicorn wind_backend.main:app --reload --host 127.0.0.1 --port 8000
```

The first command only prints enabled/configured flags and model ID. `--live`
uses synthetic forecasts, runs the tool-calling loop, and exits nonzero on failure.
It sends data to NVIDIA and consumes API requests. It does not train a power model,
load private SCADA, or change the registry. `GET /api/v1/agent/status` provides the
same secret-free configuration status, not proof of successful authentication.

## What the agent does

After numerical coverage, bounds and provenance checks, Nemotron chooses between
two read-only tools and must use both before writing a report:

- `forecast_summary`: computed min/max/mean/first/last normalized power and counts
  for each turbine and 24-hour horizon.
- `quality_audit`: deterministic coverage counts, prediction algorithm/cutoff,
  weather initialization/publication/verification metadata, warnings and demo flag.

Only these aggregates are sent. Raw SCADA, complete hourly arrays, free-form weather
evidence, filesystem paths and credentials are not tool inputs. The tools accept
no arguments and cannot fetch arbitrary files, execute commands, retrain models,
approve weather archives or change predictions. The report is advisory text in
`ForecastResult.analysis`, separate from numerical points and deterministic warnings.
The dashboard shows it under **Autonomous agent → NVIDIA analysis**. Tool names
and completion status also appear in the activity log. Reports are English to
match the current dashboard; narrative claims are not numerical accuracy metrics.

At most three requests and two tool executions are allowed, with a total deadline
(default 30 seconds, configurable 1–120). Malformed responses, unrecognized tools,
truncated answers, timeout, HTTP errors or missing keys return an explicit
`unavailable` analysis; the numerical forecast remains successful. No raw provider
exception text is persisted. The default configuration is disabled and makes no
NVIDIA calls. Backtests skip NVIDIA even when enabled, because numerical scoring
does not need an LLM call for every replay day.

Analysis does not participate in the physical input fingerprint. Changing the
NVIDIA configuration does not make unchanged-input refresh retrigger analysis;
submit a new forecast to obtain a new report. Old saved forecasts remain readable
with `analysis=null`. Disabling the analyst does not remove already saved reports.

## Models in another clone

Installing dependencies does not install trained weights. Model files, SQLite
registry and prepared source data are local. If only Demo power curve appears,
check `WINDFARM_DB` and `WINDFARM_MODELS` from that checkout, then follow
[training reproduction](ml-training.md). A teammate must reproduce training or
transfer matching model artifacts **and** registry/source history, not just `.cbm`
files. NVIDIA credentials do not recover those missing artifacts.

## Verification

Offline tests use `httpx.MockTransport` for tool selection, malformed/unauthorized
calls, missing keys, provider errors, timeout, persistence, replay exclusion and
unchanged numerical forecasts. A live success must be verified with your own key;
passing mocked tests alone does not prove access to NVIDIA's endpoint.
