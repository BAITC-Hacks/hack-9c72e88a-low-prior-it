import type { BacktestRun, ForecastRun, Turbine } from '../../src/api';

export const turbines: Turbine[] = [
  { id: 'turbine-1', name: 'Turbine 1', country_code: 'KZ', country_name: 'Kazakhstan', site_id: 'wind-site', site_name: 'Wind site', latitude: 43.645139, longitude: 78.535611 },
  { id: 'turbine-2', name: 'Turbine 2', country_code: 'KZ', country_name: 'Kazakhstan', site_id: 'wind-site', site_name: 'Wind site', latitude: 43.643198, longitude: 78.538828 },
];

export const request = {
  turbine_ids: ['turbine-1'], issued_at: '2026-01-31T00:00:00Z',
  horizon_hours: 48 as const, weather_source: 'demo' as const, model_id: 'demo-power-curve',
};

export function forecast(id = 'run-saved', status: ForecastRun['status'] = 'succeeded'): ForecastRun {
  return { id, created_at: '2026-01-31T00:00:00Z', status, request, events: [], result: null, error: null };
}

export function replay(status: BacktestRun['status']): BacktestRun {
  return {
    id: 'replay-test', created_at: '2026-01-31T00:00:00Z', status, is_demo: true,
    request: { ...request, last_issued_at: '2026-02-28T00:00:00Z', evaluation_start: '2026-02-01T00:00:00Z', evaluation_end: '2026-03-01T00:00:00Z', actuals_dataset_id: null },
    forecast_ids: status === 'succeeded' ? ['run-daily'] : [], metrics: [], scored_points: 0, unscored_points: 0,
  };
}
