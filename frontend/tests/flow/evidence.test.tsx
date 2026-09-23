import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { api, type EvidenceReport } from '../../src/api';
import EvidenceView from '../../src/evidence/EvidenceView';

vi.mock('../../src/api', () => ({ api: { evidence: vi.fn() } }));

const digest = 'a'.repeat(64);

function evidenceFixture(): EvidenceReport {
  const models: EvidenceReport['benchmark']['models'] = [
    { id: 'constant', label: 'Constant (training median)', selected: false, mae: .20 },
    { id: 'climatology', label: 'Climatology (turbine × UTC hour)', selected: false, mae: .24 },
    { id: 'persistence', label: 'Persistence', selected: false, mae: .30 },
    { id: 'scada', label: 'CatBoost SCADA', selected: false, mae: .29 },
    { id: 'weather_scada', label: 'CatBoost weather + SCADA', selected: true, mae: .25 },
  ].map(model => ({
    ...model, id: model.id as EvidenceReport['benchmark']['models'][number]['id'],
    scored_pairs_sha256: digest, pooled: { samples: 4, mae: model.mae, rmse: model.mae },
    metrics: ['turbine-1', 'turbine-2'].flatMap(turbine_id => (['1-24', '25-48'] as const).map(horizon => ({ turbine_id, horizon, samples: 1, mae: model.mae, rmse: model.mae }))),
  }));
  return {
    status: 'provisional', source_file: 'fixture.json', source_sha256: digest,
    selected_at: '2026-01-01T00:00:00Z',
    benchmark: { name: 'Fixture comparison', first_issue: '2026-01-01T12:00:00Z', last_issue: '2026-01-29T12:00:00Z', issue_step_hours: 24, horizon_hours: 48, trained_through: '2026-01-01T00:00:00Z', feature_set: 'weather-scada', reused_comparison: true, scored_pairs: 4, unscored_pairs: 0, models },
    selection: { objective: 'Development MAE only', first_training_origin: '2024-03-14T12:00:00Z', candidates: [] },
    data: { complete_hours: 4, timezone: 'Etc/GMT-6', timestamp_position: 'start', latency_minutes: 10, provisional: true, history_sha256: digest, sources: [] },
    refit: { trained_through: '2026-01-31T12:00:00Z', training_rows: 4, evaluated: false },
    weather: { source: 'Fixture archive', model: 'ECMWF', source_sha256: digest, run_hour_utc: 0, issue_hour_utc: 12, publication_delay_hours: 8, availability_basis: 'Availability is inferred from a schedule, not verified per run.', limitations: ['No February actuals.'] },
    checkpoints: [], limitations: ['No February actuals.'],
  };
}

it('shows all five models and reports a weather model losing to a constant', async () => {
  vi.mocked(api.evidence).mockResolvedValue(evidenceFixture());
  render(<EvidenceView />);
  await screen.findByText('25.0% higher MAE than Constant (training median)');
  const comparison = screen.getByRole('table', { name: /Chronological model comparison/ });
  expect(within(comparison).getAllByRole('row')).toHaveLength(6);
  expect(within(comparison).getByText('Climatology (turbine × UTC hour)')).toBeTruthy();
  expect(within(comparison).getByText('CatBoost SCADA')).toBeTruthy();
  expect(within(comparison).getByText('CatBoost weather + SCADA').closest('tr')?.className).toContain('evidence-selected-row');
  expect(screen.getByText('Availability is inferred from a schedule, not verified per run.')).toBeTruthy();
  fireEvent.change(screen.getByRole('combobox', { name: 'Turbine' }), { target: { value: 'turbine-2' } });
  fireEvent.change(screen.getByRole('combobox', { name: 'Lead window' }), { target: { value: '25-48' } });
  expect(screen.getByText('25.0% higher MAE than Constant (training median)')).toBeTruthy();
  expect(within(comparison).getAllByRole('cell', { name: '1' })).toHaveLength(5);
});
