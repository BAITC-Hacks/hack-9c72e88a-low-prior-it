from collections import defaultdict
from math import sqrt

from wind_contracts import Metric


def evaluate(points, actuals):
    truth = {(r.turbine_id, r.valid_time): r.power_normalized for r in actuals}
    groups = defaultdict(list)
    for point in points:
        groups[(point.turbine_id, "1-24" if point.lead_hours <= 24 else "25-48")].append(point)
    metrics = []
    for (turbine_id, horizon), values in sorted(groups.items()):
        errors = [p.power_normalized - truth[(p.turbine_id, p.valid_time)]
                  for p in values if (p.turbine_id, p.valid_time) in truth]
        n = len(errors)
        metrics.append(Metric(turbine_id=turbine_id, horizon=horizon, predicted=len(values), scored=n,
            missing=len(values) - n, mae=sum(abs(e) for e in errors) / n if n else None,
            rmse=sqrt(sum(e * e for e in errors) / n) if n else None))
    return metrics
