import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import App from '../../src/App';
import { api } from '../../src/api';
import { forecast, request, turbines } from './fixtures';

vi.mock('../../src/api', () => ({ api: {
  assets: vi.fn(), turbines: vi.fn(), models: vi.fn(), forecasts: vi.fn(), backtests: vi.fn(), datasets: vi.fn(), createForecast: vi.fn(), forecast: vi.fn(), evidence: vi.fn(),
} }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.assets).mockResolvedValue(turbines.map(t => ({ ...t, energy_type: 'wind', forecast_supported: true, forecast_turbine_id: t.id })));
  vi.mocked(api.turbines).mockResolvedValue(turbines);
  vi.mocked(api.models).mockResolvedValue([]);
  vi.mocked(api.forecasts).mockResolvedValue([]);
  vi.mocked(api.backtests).mockResolvedValue([]);
  vi.mocked(api.datasets).mockResolvedValue([]);
  vi.mocked(api.evidence).mockRejectedValue(new Error('Evidence fixture unavailable'));
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ features: [{
    type: 'Feature', properties: { code: 'KZ', name: 'Kazakhstan', lat: 49, lng: 68, span: 27 },
    geometry: { type: 'Polygon', coordinates: [] },
  }] }) }));
});

it('returns to Explore with browser Back after the first workspace transition', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: 'Energy explorer' });
  expect(window.location.hash).toBe('#explore');
  fireEvent.click(screen.getByRole('link', { name: 'Forecast' }));
  await screen.findByRole('heading', { name: 'Forecast workspace' });
  act(() => window.history.back());
  await waitFor(() => expect(window.location.hash).toBe('#explore'));
  expect(screen.getByRole('heading', { name: 'Energy explorer' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Forecast workspace' })).toBeNull();
});

it('normalizes an unknown URL section to Explore', async () => {
  window.history.replaceState(null, '', '/#unknown-section');
  render(<App />);
  await screen.findByRole('heading', { name: 'Energy explorer' });
  expect(window.location.hash).toBe('#explore');
  expect(screen.getByRole('link', { name: 'Explore' }).getAttribute('aria-current')).toBe('location');
});

it('preserves the Evidence deep link and returns there with Back', async () => {
  window.history.replaceState(null, '', '/#evidence');
  render(<App />);
  await screen.findByRole('heading', { name: 'Model evidence' });
  expect(window.location.hash).toBe('#evidence');
  expect(screen.queryByRole('heading', { name: 'Forecast workspace' })).toBeNull();
  fireEvent.click(screen.getByRole('link', { name: 'Forecast' }));
  await screen.findByRole('heading', { name: 'Forecast workspace' });
  act(() => window.history.back());
  await waitFor(() => expect(window.location.hash).toBe('#evidence'));
  expect(screen.getByRole('heading', { name: 'Model evidence' })).toBeTruthy();
});

it('restores the saved Evidence workspace on a new visit', async () => {
  localStorage.setItem('low-prior-view', 'evidence');
  render(<App />);
  await screen.findByRole('heading', { name: 'Model evidence' });
  expect(window.location.hash).toBe('#evidence');
});

it('opens the forecast workspace for an Insights deep link', async () => {
  window.history.replaceState(null, '', '/#insights');
  render(<App />);
  await screen.findByRole('heading', { name: 'Forecast workspace' });
  expect(window.location.hash).toBe('#insights');
  const insights = document.getElementById('insights');
  expect(insights).not.toBeNull();
  expect(insights!.closest('[hidden]')).toBeNull();
});

it('selects a country and turbine, runs a 24-hour forecast, and exposes its results and export', async () => {
  const submitted = { ...request, issued_at: '2026-01-31T12:00:00.000Z', horizon_hours: 24 as const, turbine_ids: ['turbine-2'] };
  const queued = { ...forecast('run-journey', 'queued'), request: submitted };
  vi.mocked(api.createForecast).mockResolvedValue(queued);
  vi.mocked(api.forecast).mockResolvedValue({ ...queued, status: 'succeeded', result: {
    model_id: 'demo-power-curve', input_fingerprint: 'test-fixture', is_demo: true, snapshots: [], warnings: [],
    points: Array.from({ length: 24 }, (_, index) => ({ turbine_id: 'turbine-2', lead_hours: index + 1, valid_time: new Date(Date.parse(submitted.issued_at) + (index + 1) * 3600000).toISOString(), power_normalized: .5 })),
  } });
  render(<App />);
  await screen.findByRole('option', { name: 'Kazakhstan' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Select country' }), { target: { value: 'KZ' } });
  fireEvent.click(await screen.findByRole('button', { name: /Wind site 2 turbines/ }));
  fireEvent.click(screen.getByRole('checkbox', { name: /Turbine 1/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Open forecast' }));
  await screen.findByRole('heading', { name: 'Forecast workspace' });
  fireEvent.click(screen.getByRole('button', { name: '24h' }));
  fireEvent.click(screen.getByRole('button', { name: 'Run forecast' }));
  await waitFor(() => expect(api.createForecast).toHaveBeenCalledWith(expect.objectContaining(submitted)));
  const csv = await screen.findByRole('link', { name: 'Export CSV' }, { timeout: 3000 });
  expect(csv.getAttribute('href')).toBe('/api/v1/forecasts/run-journey/export');
  expect(screen.getByRole('heading', { name: '24-hour power forecast' })).toBeTruthy();
  const hourly = screen.getByRole('region', { name: 'Hourly forecast' });
  expect(within(hourly).getByText('24 predictions · UTC')).toBeTruthy();
  expect(within(hourly).queryByText('Turbine 1')).toBeNull();
  expect(screen.queryByText('Demo data.')).toBeNull();
});

it('global refresh reloads Explore assets and shows feedback in the visible workspace', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: 'Energy explorer' });
  await waitFor(() => expect((screen.getByRole('button', { name: 'Refresh workspace data' }) as HTMLButtonElement).disabled).toBe(false));
  await waitFor(() => expect(api.assets).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh workspace data' }));
  await waitFor(() => expect(api.assets).toHaveBeenCalledTimes(2));
  const feedback = await screen.findByText('Workspace data refreshed.');
  expect(feedback.closest('[hidden]')).toBeNull();
});

it('connection errors remain visible in Explore and Refresh can recover', async () => {
  vi.mocked(api.models).mockRejectedValueOnce(new Error('Service offline'));
  render(<App />);
  await screen.findByRole('heading', { name: 'Energy explorer' });
  const error = await screen.findByText(/Cannot connect to the forecasting service/);
  expect(error.closest('[hidden]')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh workspace data' }));
  await screen.findByText('Workspace data refreshed.');
  expect(screen.queryByText(/Cannot connect to the forecasting service/)).toBeNull();
});

it('keeps keyboard focus in the directory when a selected country search result disappears', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: 'Energy explorer' });
  await screen.findByRole('option', { name: 'Kazakhstan' });
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search countries' }), { target: { value: 'kaz' } });
  const result = within(screen.getByLabelText('Matching countries')).getByRole('button');
  result.focus();
  fireEvent.click(result);
  await waitFor(() => {
    const directory = screen.getByRole('complementary', { name: 'Country and station directory' });
    expect(directory.contains(document.activeElement)).toBe(true);
  });
  expect(document.activeElement).not.toBe(document.body);
});
