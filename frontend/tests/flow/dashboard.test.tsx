import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../../src/api';
import useDashboard from '../../src/useDashboard';
import { forecast, replay, turbines } from './fixtures';

vi.mock('../../src/api', () => ({ api: {
  turbines: vi.fn(), models: vi.fn(), forecasts: vi.fn(), backtests: vi.fn(), datasets: vi.fn(),
  createForecast: vi.fn(), forecast: vi.fn(), createBacktest: vi.fn(), backtest: vi.fn(), refresh: vi.fn(),
} }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.turbines).mockResolvedValue(turbines);
  vi.mocked(api.models).mockResolvedValue([]);
  vi.mocked(api.forecasts).mockResolvedValue([]);
  vi.mocked(api.backtests).mockResolvedValue([]);
  vi.mocked(api.datasets).mockResolvedValue([]);
});

it('hands an explorer selection to a forecast without adding the other turbine', async () => {
  vi.mocked(api.createForecast).mockResolvedValue(forecast('run-created'));
  const { result } = renderHook(useDashboard);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.chooseTurbines(['turbine-2']));
  await act(() => result.current.submitForecast());
  expect(api.createForecast).toHaveBeenCalledWith(expect.objectContaining({ turbine_ids: ['turbine-2'], horizon_hours: 48 }));
});

it('February replay uses its own fixed origin when the forecast issue input is empty', async () => {
  vi.mocked(api.createBacktest).mockResolvedValue(replay('queued'));
  const { result } = renderHook(useDashboard);
  await waitFor(() => expect(result.current.connected).toBe(true));
  act(() => result.current.setIssue(''));
  await act(() => result.current.startReplay(null));
  expect(api.createBacktest).toHaveBeenCalledWith(expect.objectContaining({ issued_at: '2026-01-31T00:00:00.000Z' }));
  expect(result.current.error).toBe('');
});

it.each(['succeeded', 'failed'] as const)('loads daily results once after a %s replay without replacing edited controls', async status => {
  const saved = forecast();
  vi.mocked(api.forecasts).mockResolvedValueOnce([saved]).mockResolvedValue([forecast('run-daily'), saved]);
  vi.mocked(api.backtests).mockResolvedValue([replay('running')]);
  vi.mocked(api.backtest).mockResolvedValue(replay(status));
  const { result } = renderHook(useDashboard);
  await waitFor(() => expect(result.current.connected).toBe(true));
  act(() => { result.current.setIssue('2026-02-10T12:00'); result.current.setHorizon(24); });
  await waitFor(() => expect(result.current.history.some(run => run.id === 'run-daily')).toBe(true), { timeout: 4000 });
  expect(api.forecasts).toHaveBeenCalledTimes(2);
  expect(result.current.run?.id).toBe(saved.id);
  expect(result.current.issue).toBe('2026-02-10T12:00');
  expect(result.current.horizon).toBe(24);
});

it('marks failed refresh disconnected and can reconnect without losing turbine selection', async () => {
  const { result } = renderHook(useDashboard);
  await waitFor(() => expect(result.current.connected).toBe(true));
  act(() => result.current.chooseTurbines(['turbine-2']));
  vi.mocked(api.turbines).mockRejectedValueOnce(new Error('Offline'));
  await act(() => result.current.reloadWorkspace());
  expect(result.current.connected).toBe(false);
  expect(result.current.error).toContain('Offline');
  await act(() => result.current.reloadWorkspace());
  expect(result.current.connected).toBe(true);
  expect(result.current.selected).toEqual(['turbine-2']);
});
