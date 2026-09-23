from collections import defaultdict
from math import sqrt
from statistics import mean

from wind_contracts.models import ForecastPoint, Metric, Observation


def evaluate(points: list[ForecastPoint], actuals: list[Observation]):
    observed = {(row.turbine_id, row.valid_time): row.power_normalized for row in actuals}
    if len(observed) != len(actuals):
        raise ValueError("Duplicate turbine/time actuals would make scoring ambiguous")
    errors = defaultdict(list)
    missing = 0
    for point in points:
        actual = observed.get((point.turbine_id, point.valid_time))
        if actual is None:
            missing += 1
            continue
        horizon = "1-24" if point.lead_hours <= 24 else "25-48"
        errors[(point.turbine_id, horizon)].append(point.power_normalized - actual)
    metrics = [
        Metric(
            turbine_id=turbine,
            horizon=horizon,
            samples=len(values),
            mae=mean(abs(value) for value in values),
            rmse=sqrt(mean(value * value for value in values)),
        )
        for (turbine, horizon), values in sorted(errors.items())
    ]
    return metrics, len(points) - missing, missing
