from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from wind_agent.scada import aggregate_hourly
from wind_agent.source_data import local_to_utc, read_organizer_csv, source_timezone


def test_almaty_historical_offsets_and_ambiguous_hour():
    zone = ZoneInfo("Asia/Almaty")
    assert local_to_utc(datetime(2023, 3, 11, 6), zone) == datetime(2023, 3, 11, tzinfo=UTC)
    assert local_to_utc(datetime(2026, 1, 1, 5), zone) == datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="Ambiguous"):
        local_to_utc(datetime(2024, 2, 29, 23, 10), zone)


def test_organizer_adapter_records_quarantine_and_latency(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text(
        "ID,Статистическое время,Средняя скорость ветра(m/s),Нормализованная активная мощность,Средняя температура окружающей среды(°C)\n"
        "1,2026-01-01 5:00:00,8,0.5,-5\n2,2024-02-29 23:10:00,8,0.5,-5\n",
        encoding="utf-8-sig",
    )
    kwargs = dict(
        turbine_id="turbine-1",
        timezone="Asia/Almaty",
        timestamp_position="start",
        latency_minutes=10,
    )
    with pytest.raises(ValueError, match="invalid source rows"):
        read_organizer_csv(path, **kwargs)
    rows, report = read_organizer_csv(path, quarantine_invalid=True, **kwargs)
    assert rows[0].valid_time == datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    assert rows[0].available_at == datetime(2026, 1, 1, 0, 20, tzinfo=UTC)
    assert report["quarantined_rows"] == 1
    assert report["issues"][0]["line"] == 3


@pytest.mark.parametrize(
    "moment", [datetime(2023, 3, 11, 6), datetime(2024, 2, 29, 23, 10), datetime(2026, 1, 1, 6)]
)
def test_fixed_utc6_does_not_follow_almaty_civil_time_changes(moment):
    from datetime import timedelta

    assert local_to_utc(moment, source_timezone("UTC+06:00")) == (
        moment - timedelta(hours=6)
    ).replace(tzinfo=UTC)


@pytest.mark.parametrize("name", ["UTC+6", "UTC+24:00", "UTC+06:60"])
def test_invalid_fixed_offsets_fail(name):
    with pytest.raises(ValueError):
        source_timezone(name)


def test_fixed_utc6_interval_starts_produce_complete_hour(tmp_path):
    path = tmp_path / "source.csv"
    header = "ID,Статистическое время,Средняя скорость ветра(m/s),Нормализованная активная мощность,Средняя температура окружающей среды(°C)\n"
    path.write_text(
        header + "".join(f"{i},2026-01-01 5:{i * 10:02d}:00,8,0.5,-5\n" for i in range(6)),
        encoding="utf-8",
    )
    rows, report = read_organizer_csv(
        path,
        turbine_id="turbine-1",
        timezone="UTC+06:00",
        timestamp_position="start",
        latency_minutes=10,
    )
    hours = aggregate_hourly(rows)
    assert report["quarantined_rows"] == 0
    assert len(hours) == 1 and hours[0].complete
    assert hours[0].valid_time == datetime(2026, 1, 1, tzinfo=UTC)
    assert hours[0].available_at == datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    assert hours[0].power_mean == 0.5
