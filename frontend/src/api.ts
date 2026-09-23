import type { components, paths } from './generated/api';

type Schemas = components['schemas'];
export type Turbine = Schemas['Turbine'];
export type ForecastRun = Schemas['ForecastRun'];
export type BacktestRun = Schemas['BacktestRun'];
export type ForecastRequest = Schemas['ForecastRequest'];
export type ModelInfo = Schemas['ModelInfo'];

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.message || `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

// Paths and payload types are checked against generated OpenAPI contracts.
const routes = {
  turbines: '/api/v1/turbines',
  models: '/api/v1/models',
  forecasts: '/api/v1/forecasts',
  backtests: '/api/v1/backtests',
} satisfies Record<string, keyof paths>;

export const api = {
  turbines: () => request<Turbine[]>(routes.turbines.slice(7)),
  models: () => request<ModelInfo[]>(routes.models.slice(7)),
  forecasts: () => request<ForecastRun[]>(routes.forecasts.slice(7)),
  forecast: (id: string) => request<ForecastRun>(`/forecasts/${encodeURIComponent(id)}`),
  createForecast: (body: ForecastRequest) => request<ForecastRun>('/forecasts', body),
  refresh: (id: string) => request<Schemas['RefreshResponse']>(`/forecasts/${encodeURIComponent(id)}/refresh`, {}),
  createBacktest: (body: Schemas['BacktestRequest']) => request<BacktestRun>('/backtests', body),
  backtest: (id: string) => request<BacktestRun>(`/backtests/${encodeURIComponent(id)}`),
};
