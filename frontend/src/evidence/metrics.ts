type ScoredGroup = { turbine_id: string; horizon: string; samples: number; mae: number; rmse: number };
type Score = { samples: number; mae: number; rmse: number };

/** Pool errors over observations; averaging group RMSE values is mathematically wrong. */
export function poolMetrics(metrics: readonly ScoredGroup[]): Score | null {
  const samples = metrics.reduce((sum, metric) => sum + metric.samples, 0);
  if (!samples) return null;
  return {
    samples,
    mae: metrics.reduce((sum, metric) => sum + metric.mae * metric.samples, 0) / samples,
    rmse: Math.sqrt(metrics.reduce((sum, metric) => sum + metric.rmse ** 2 * metric.samples, 0) / samples),
  };
}

/** Relative error comparisons require matching turbine, horizon, and sample cells. */
export function sameCoverage(left: readonly ScoredGroup[], right: readonly ScoredGroup[]) {
  const key = (metric: ScoredGroup) => `${metric.turbine_id}:${metric.horizon}`;
  if (!left.length || left.length !== right.length || new Set(left.map(key)).size !== left.length || new Set(right.map(key)).size !== right.length) return false;
  return left.every(metric => right.some(other => key(other) === key(metric) && other.samples === metric.samples));
}
