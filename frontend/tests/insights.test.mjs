import assert from 'node:assert/strict';
import test from 'node:test';
import { deriveForecastSignals, forecastBrief } from '../src/insights.ts';

const origin = Date.parse('2026-01-31T22:00:00Z');
function runFor(series, changes = {}) {
  return {
    id: 'run-test', status: 'succeeded',
    request: { turbine_ids: Object.keys(series), issued_at: new Date(origin).toISOString(), horizon_hours: 24, model_id: 'test-model', weather_source: 'demo' },
    result: { is_demo: true, model_id: 'test-model', input_fingerprint: 'test-fingerprint', snapshots: [], warnings: ['Synthetic input.'], points: Object.entries(series).flatMap(([turbine_id, values]) => values.map((power_normalized, index) => ({ turbine_id, power_normalized, lead_hours: index + 1, valid_time: new Date(origin + (index + 1) * 3_600_000).toISOString() }))) },
    ...changes,
  };
}

test('windows use complete equal-weight turbine means and physical UTC interval boundaries', () => {
  const run = runFor({ a: [0, .2, .4, .8, 1, .1], b: [.2, .4, .6, 1, .8, .1] });
  const signals = deriveForecastSignals(run);
  assert.equal(signals.hours.length, 6);
  assert.equal(signals.assetCount, 2);
  assert.equal(signals.expectedHours, 24);
  assert.equal(signals.high.firstLead, 3);
  assert.equal(signals.high.lastLead, 5);
  assert.equal(signals.high.start, '2026-02-01T00:00:00.000Z');
  assert.equal(signals.high.end, '2026-02-01T03:00:00.000Z');
  assert.ok(Math.abs(signals.high.mean - 2.3 / 3) < 1e-12);
  assert.equal(signals.low.firstLead, 1);
  assert.equal(signals.ramp.toLead, 6);
  assert.equal(signals.ramp.delta, -.8);
});

test('gaps never bridge three-hour windows or one-hour ramps', () => {
  const run = runFor({ a: [.1, .2, .3, .9, .9], b: [.1, .2, .3, .9, .9] });
  run.result.points = run.result.points.filter(point => !(point.turbine_id === 'b' && point.lead_hours === 3));
  const signals = deriveForecastSignals(run);
  assert.deepEqual(signals.hours.map(hour => hour.lead), [1, 2, 4, 5]);
  assert.equal(signals.high, null);
  assert.equal(signals.low, null);
  assert.equal(signals.ramp.toLead, 2);
  assert.equal(signals.ramp.delta, .1);
});

test('duplicate turbine-hour is excluded instead of overweighting one turbine', () => {
  const run = runFor({ a: [.1, .2, .3], b: [.1, .2, .3] });
  run.result.points.push({ ...run.result.points[1] });
  assert.deepEqual(deriveForecastSignals(run).hours.map(hour => hour.lead), [1, 3]);
  assert.equal(deriveForecastSignals(run).ramp, null);
});

test('timestamp mismatch and invalid values cannot become planning signals', () => {
  for (const bad of [{ power_normalized: NaN }, { power_normalized: Infinity }, { power_normalized: -1 }, { power_normalized: 2 }, { valid_time: 'invalid' }, { valid_time: new Date(origin).toISOString() }]) {
    const run = runFor({ a: [.1, .2, .3] });
    Object.assign(run.result.points[1], bad);
    assert.deepEqual(deriveForecastSignals(run).hours.map(hour => hour.lead), [1, 3]);
  }
});

test('unexpected turbines and out-of-horizon points do not alter the requested fleet', () => {
  const run = runFor({ a: [.2, .2, .2] });
  run.result.points.push({ ...run.result.points[0], turbine_id: 'unrequested', power_normalized: 1 });
  for (const lead of [0, 25, .5]) run.result.points.push({ ...run.result.points[0], lead_hours: lead });
  const signals = deriveForecastSignals(run);
  assert.equal(signals.hours.length, 3);
  assert.ok(Math.abs(signals.high.mean - .2) < 1e-12);
  assert.equal(signals.ramp.delta, 0);
});

test('ties resolve to the earliest window and ramp regardless of point order', () => {
  const run = runFor({ a: [.5, .5, .5, .5, .5] });
  run.result.points.reverse();
  const signals = deriveForecastSignals(run);
  assert.equal(signals.high.firstLead, 1);
  assert.equal(signals.low.firstLead, 1);
  assert.equal(signals.ramp.toLead, 2);
});

test('pending, failed, empty and malformed runs have no publishable signals', () => {
  assert.equal(deriveForecastSignals(null).high, null);
  for (const status of ['running', 'failed', 'queued']) assert.equal(deriveForecastSignals(runFor({ a: [.8, .8, .8] }, { status })).hours.length, 0);
  assert.equal(deriveForecastSignals(runFor({})).hours.length, 0);
  const duplicate = runFor({ a: [.8, .8, .8] });
  duplicate.request.turbine_ids.push('a');
  assert.equal(deriveForecastSignals(duplicate).hours.length, 0);
  for (const horizon of [1, 1000000000, Infinity, NaN]) {
    const run = runFor({ a: [.8, .8, .8] });
    run.request.horizon_hours = horizon;
    assert.equal(deriveForecastSignals(run).hours.length, 0);
    assert.equal(deriveForecastSignals(run).expectedHours, 48);
  }
});

test('portable brief retains demo status, model, issue, lineage and aggregation limitations', () => {
  const run = runFor({ a: [.2, .4, .9] });
  run.result.snapshots = [{ id: 'snapshot-test', turbine_id: 'a', weather_model: 'synthetic-v1', verification: 'synthetic', run_init: new Date(origin).toISOString(), available_at: null }];
  const brief = forecastBrief(run);
  for (const expected of ['DEMO / PROVISIONAL', 'run-test', 'test-model', 'test-fingerprint', '2026-01-31T22:00', 'snapshot-test', 'unverified', 'percentage points', 'not capacity-weighted', 'No calibrated uncertainty', 'Synthetic input.']) assert.ok(brief.includes(expected), expected);
});
