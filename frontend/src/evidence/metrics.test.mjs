import assert from 'node:assert/strict';
import test from 'node:test';
import { poolMetrics, sameCoverage } from './metrics.ts';

const first = { turbine_id: 'turbine-1', horizon: '1-24', samples: 3, mae: 0.1, rmse: 0.2 };
const second = { turbine_id: 'turbine-2', horizon: '25-48', samples: 1, mae: 0.5, rmse: 0.6 };

test('pooled errors weight observations and pool squared errors before taking the root', () => {
  const pooled = poolMetrics([first, second]);
  assert.equal(pooled.samples, 4);
  assert.ok(Math.abs(pooled.mae - 0.2) < 1e-12);
  assert.ok(Math.abs(pooled.rmse - Math.sqrt(0.12)) < 1e-12);
  assert.notEqual(pooled.rmse, (first.rmse + second.rmse) / 2);
});

test('empty selections have no score', () => {
  assert.equal(poolMetrics([]), null);
});

test('matching coverage is independent of ordering and error values', () => {
  assert.equal(sameCoverage([first, second], [{ ...second, mae: 0.4 }, { ...first, mae: 0.05 }]), true);
});

test('equal total samples cannot hide mismatched turbine, horizon, or cell counts', () => {
  assert.equal(sameCoverage([first, second], [{ ...first, samples: 2 }, { ...second, samples: 2 }]), false);
  assert.equal(sameCoverage([first], [{ ...first, turbine_id: 'turbine-2' }]), false);
  assert.equal(sameCoverage([first], [{ ...first, horizon: '25-48' }]), false);
  assert.equal(sameCoverage([first, first], [first, first]), false);
  assert.equal(sameCoverage([], []), false);
});
