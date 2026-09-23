# PR title

Add optional OpenAI and NVIDIA forecast analysis with bounded read-only tools

## Change

Completed forecasts can now include an advisory report from OpenAI or NVIDIA NIM.
The selected numerical model still computes every power value; the cloud analyst
receives computed summaries and provenance checks after prediction and validation.
The dashboard displays the report, provider, model and availability status.

Both providers are disabled by default. Enable exactly one in the backend `.env`.
OpenAI uses `gpt-4.1-mini` through Responses; NVIDIA remains an alternative adapter.
The existing `httpx` dependency handles both providers, with no extra SDK or GPU.

The analyst must call `forecast_summary` and `quality_audit` before reporting.
Each analysis permits at most three API requests and two read-only tool executions,
with a total deadline. Missing keys, provider errors, timeouts, incomplete tool
calls and malformed reports preserve the numerical forecast and mark the analysis
unavailable. Historical backtests skip cloud analysis.

## Contracts and integration

- Add `GET /api/v1/agent/status` with provider/configuration flags, never API keys.
- Add optional `ForecastResult.analysis`; old stored forecasts remain readable.
- Regenerate OpenAPI and frontend types; report text renders as plain React text.
- Keep numerical fingerprints, temporal validation and weather verification outside
  the LLM. Analyst configuration changes require a new forecast for a new report.
- Add provider setup guides and configuration/live-check commands. Correct the
  outdated README statement that the project has no LLM integration.
- Integrate `origin/main` at `d0cffe7` without conflicts, preserving author setup docs.
- Existing trained CatBoost results and reproduction instructions remain in
  [ML training](ml-training.md) and [tuning results](tuned-training-results.md).

## Validation

Checked locally on Windows on 2026-09-23:

- `python scripts/run_tests.py`: **158 passed**. Offline provider fixtures cover
  both tool-call patterns, incomplete/malformed replies, timeouts, credential
  redaction, unchanged power values, persistence and omission during backtests.
- `ruff check .` and offline `uv lock --check`: passed.
- `npm run test --workspace frontend`: **7 passed**.
- `npm run build`: passed, including TypeScript checks.
- Regenerated OpenAPI and TypeScript match committed contracts; `git diff --check`
  passes and tracked sources contain no unresolved merge markers or local API keys.
- HTTP smoke test on an isolated temporary database: health, two turbines,
  96 forecast points, unchanged-input refresh, 29 daily demo forecasts and
  2,686 exported February issue/target pairs. Cloud providers disabled for this test.
- The user supplied a successful OpenAI live smoke-test log with both tools and
  `analysis.status=succeeded`; no additional paid requests were needed for review.

## Limitations and handoff

NVIDIA has offline coverage only; live access was unavailable for this account.
OpenAI smoke testing establishes connectivity, not numerical forecast accuracy.
The task.pdf requirement for verified historical weather forecasts and February
evaluation remains open. Synthetic weather and provisional model assumptions
retain their labels; the LLM cannot certify archive availability or supply missing
weather. Reports are advisory English text.

Existing dependency deprecation warnings (Starlette/httpx and pandas/NumPy) and
the large globe bundle warning remain; they do not fail the checks.

Secrets, local datasets, SQLite state and trained weights are excluded from this
change. A fresh clone must reproduce training or receive matching authorized
model artifacts and registry/data separately. See [OpenAI setup](openai-agent.md)
and [NVIDIA setup](nvidia-agent.md) for per-machine analyst configuration.

Base: `main`. Head: `ml-aiagent`. This file is the prepared PR description;
remote push, PR publication and merge into main are left to the maintainer.
