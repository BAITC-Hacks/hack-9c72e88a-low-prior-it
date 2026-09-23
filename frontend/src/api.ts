import type { components } from './generated/api';
export type Schema<K extends keyof components['schemas']> = components['schemas'][K];
const BASE = '/api/v1';
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(BASE + path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: response.statusText }));
    throw new Error(error.message ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}
export const api = {
  turbines: () => request<Schema<'Turbine'>[]>('/turbines'),
  datasets: () => request<Schema<'DatasetInfo'>[]>('/datasets'),
  models: () => request<Schema<'ModelInfo'>[]>('/models'),
  forecasts: () => request<Schema<'ForecastRun'>[]>('/forecasts'),
  backtests: () => request<Schema<'BacktestRun'>[]>('/backtests'),
  weather: () => request<Schema<'WeatherSnapshot'>[]>('/weather/snapshots'),
  importDataset: (body: Schema<'DatasetImport'>) => request<Schema<'DatasetInfo'>>('/datasets', body),
  train: (body: Schema<'TrainRequest'>) => request<Schema<'ModelInfo'>>('/models/train', body),
  forecast: (body: Schema<'ForecastRequest'>) => request<Schema<'ForecastRun'>>('/forecasts', body),
  run: (id: string) => request<Schema<'ForecastRun'>>(`/forecasts/${encodeURIComponent(id)}`),
  refresh: (id: string) => request<Schema<'ForecastRun'>>(`/forecasts/${encodeURIComponent(id)}/refresh`, {}),
  replay: (body: Schema<'BacktestRequest'>) => request<Schema<'BacktestRun'>>('/backtests', body),
  backtest: (id: string) => request<Schema<'BacktestRun'>>(`/backtests/${encodeURIComponent(id)}`),
  importWeather: (body: Schema<'WeatherSnapshot'>) => request<Schema<'WeatherSnapshot'>>('/weather/snapshots', body),
  fetchWeather: (body: Schema<'WeatherFetch'>) => request<Schema<'WeatherSnapshot'>>('/weather/fetch', body),
  observations: (id: string, start: string, end: string) => request<Schema<'Observation'>[]>(`/datasets/${encodeURIComponent(id)}/observations?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),
  exportUrl: (kind: 'forecasts' | 'backtests', id: string) => `${BASE}/${kind}/${encodeURIComponent(id)}/export`
};
