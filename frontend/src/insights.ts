import type { ForecastRun } from './api';

const HOUR = 3_600_000;
export type SignalHour = { lead: number; validTime: string; mean: number };
export type OutputWindow = { firstLead: number; lastLead: number; start: string; end: string; mean: number };
export type OutputRamp = { fromLead: number; toLead: number; fromTime: string; toTime: string; delta: number };
export type ForecastSignals = {
  hours: SignalHour[];
  expectedHours: number;
  assetCount: number;
  high: OutputWindow | null;
  low: OutputWindow | null;
  ramp: OutputRamp | null;
};

/** Descriptive signals only: no new predictions, interpolation, capacity or revenue assumptions. */
export function deriveForecastSignals(run: ForecastRun | null): ForecastSignals {
  const horizon = run?.request.horizon_hours;
  const empty: ForecastSignals = { hours: [], expectedHours: horizon === 24 ? 24 : 48, assetCount: 0, high: null, low: null, ramp: null };
  if (!run?.result || run.status !== 'succeeded') return empty;
  if (horizon !== 24 && horizon !== 48) return empty;
  const ids = new Set(run.request.turbine_ids);
  const origin = Date.parse(run.request.issued_at);
  if (!ids.size || ids.size !== run.request.turbine_ids.length || !Number.isFinite(origin) || origin % HOUR !== 0) return empty;
  const byHour = new Map<number, Map<string, number>>();
  const invalid = new Set<number>();
  for (const point of run.result.points) {
    if (!ids.has(point.turbine_id)) continue;
    const lead = point.lead_hours;
    if (!Number.isInteger(lead) || lead < 1 || lead > run.request.horizon_hours) continue;
    const group = byHour.get(lead) ?? new Map<string, number>();
    if (group.has(point.turbine_id) || Date.parse(point.valid_time) !== origin + lead * HOUR || !Number.isFinite(point.power_normalized) || point.power_normalized < 0 || point.power_normalized > 1) invalid.add(lead);
    group.set(point.turbine_id, point.power_normalized);
    byHour.set(lead, group);
  }
  const hours: SignalHour[] = [];
  for (let lead = 1; lead <= run.request.horizon_hours; lead++) {
    const group = byHour.get(lead);
    if (!invalid.has(lead) && group?.size === ids.size) {
      hours.push({ lead, validTime: new Date(origin + lead * HOUR).toISOString(), mean: [...group.values()].reduce((sum, value) => sum + value, 0) / ids.size });
    }
  }
  let high: OutputWindow | null = null;
  let low: OutputWindow | null = null;
  let ramp: OutputRamp | null = null;
  for (let index = 0; index < hours.length; index++) {
    const current = hours[index];
    const previous = hours[index - 1];
    if (previous && current.lead === previous.lead + 1) {
      const delta = current.mean - previous.mean;
      if (!ramp || Math.abs(delta) > Math.abs(ramp.delta)) ramp = { fromLead: previous.lead, toLead: current.lead, fromTime: previous.validTime, toTime: current.validTime, delta };
    }
    const end = hours[index + 2];
    if (!end || end.lead !== current.lead + 2) continue;
    const mean = (current.mean + hours[index + 1].mean + end.mean) / 3;
    const window = { firstLead: current.lead, lastLead: end.lead, start: new Date(origin + (current.lead - 1) * HOUR).toISOString(), end: end.validTime, mean };
    if (!high || mean > high.mean) high = window;
    if (!low || mean < low.mean) low = window;
  }
  return { hours, expectedHours: run.request.horizon_hours, assetCount: ids.size, high, low, ramp };
}

export function forecastBrief(run: ForecastRun, signals = deriveForecastSignals(run)): string {
  const windowText = (value: OutputWindow | null) => value
    ? `${value.start} to ${value.end}: ${(value.mean * 100).toFixed(1)}% mean normalized output`
    : 'Unavailable: three consecutive complete hours are required.';
  const ramp = signals.ramp;
  return [
    '# Low Prior — forecast operations brief',
    '',
    `Status: ${run.result?.is_demo ? 'DEMO / PROVISIONAL — not operational guidance' : 'Forecast planning signals — review before operational use'}`,
    `Run: ${run.id}`,
    `Issued: ${run.request.issued_at}`,
    `Model: ${run.result?.model_id ?? run.request.model_id}`,
    `Input fingerprint: ${run.result?.input_fingerprint ?? 'unavailable'}`,
    `Assets: ${run.request.turbine_ids.join(', ')}`,
    `Complete hours: ${signals.hours.length}/${signals.expectedHours}`,
    '',
    '## Forecast signals',
    `Highest three-hour window: ${windowText(signals.high)}`,
    `Lowest three-hour window: ${windowText(signals.low)}`,
    `Largest adjacent-hour change: ${ramp ? `${(ramp.delta * 100).toFixed(1)} percentage points, ${ramp.fromTime} to ${ramp.toTime}` : 'Unavailable: consecutive complete hours are required.'}`,
    '',
    'The displayed portfolio signal is the equal-weight mean of turbine-normalized outputs, not capacity-weighted station production. No MW, MWh or financial savings are inferred. Hourly timestamps denote interval ends; three-hour windows show the physical interval boundaries. Missing or duplicate turbine-hours are excluded, and windows never bridge gaps. Low output does not establish safe maintenance conditions. No calibrated uncertainty is available.',
    '',
    '## Weather lineage',
    ...(run.result?.snapshots.map(snapshot => `${snapshot.turbine_id}: ${snapshot.weather_model}; ${snapshot.verification}; run ${snapshot.run_init}; available ${snapshot.available_at ?? 'unverified'}; snapshot ${snapshot.id}`) ?? []),
    '',
    '## Model and data notes',
    ...(run.result?.warnings.map(warning => `- ${warning}`) ?? []),
    '',
  ].join('\n');
}
