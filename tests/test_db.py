"""Database tests against a real Postgres (set TEST_DATABASE_URL; CI runs one).
They start from the tables as they exist in the live database."""

from datetime import timedelta

import pytest

import etl_job
import forecast
from conftest import TEST_DATABASE_URL, FakeModel, fake_api


def telemetry(db, where="TRUE"):
    return db.execute(f"SELECT timestamp, overall_intensity, half_hours, intensity_is_actual, fuel_biomass_perc "
                      f"FROM grid_telemetry WHERE {where} ORDER BY timestamp").fetchall()


def runs(db):
    return db.execute("SELECT job, status, rows_inserted, rows_updated, rows_rejected, error_message "
                      "FROM etl_runs ORDER BY id").fetchall()


class TestSchema:
    def test_upgrades_the_legacy_tables_and_is_repeatable(self, db):
        etl_job.ensure_schema(db)
        etl_job.ensure_schema(db)
        columns = {row[0] for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'grid_telemetry'")}
        assert {"fuel_biomass_perc", "intensity_is_actual", "half_hours", "overall_intensity"} <= columns
        for view in ("grid_mix_hourly", "forecast_accuracy", "forecast_skill"):
            db.execute(f"SELECT * FROM {view}").fetchall()

    def test_duplicate_hours_give_a_clear_error(self, db):
        db.execute("INSERT INTO grid_telemetry (timestamp) VALUES ('2026-01-01 10:00Z'), ('2026-01-01 10:00Z')")
        db.commit()
        with pytest.raises(RuntimeError, match="same timestamp"):
            etl_job.ensure_schema(db)


class TestPipeline:
    def test_loads_24_hours_then_changes_nothing_on_a_rerun(self, db, now, monkeypatch):
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        rows = telemetry(db)
        assert len(rows) == 24
        assert all(row[2] == 2 and row[3] is True and row[4] == 6.0 for row in rows)

        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        assert len(telemetry(db)) == 24
        assert [r[:5] for r in runs(db)] == [("etl", "success", 24, 0, 0), ("etl", "success", 0, 0, 0)]

    def test_overwrites_legacy_and_forecast_rows_with_measured_values(self, db, now, monkeypatch):
        etl_job.ensure_schema(db)
        hour = now.replace(minute=0) - timedelta(hours=3)
        # A row the old job stored (only four fuels) and one still holding a forecast.
        db.execute("INSERT INTO grid_telemetry (timestamp, overall_intensity, fuel_wind_perc) VALUES (%s, 999, 1)", (hour,))
        db.execute("INSERT INTO grid_telemetry (timestamp, overall_intensity, half_hours, intensity_is_actual) "
                   "VALUES (%s, 170, 2, false)", (hour + timedelta(hours=1),))
        db.commit()
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0), actual=140))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        assert telemetry(db, f"timestamp IN ('{hour.isoformat()}', '{(hour + timedelta(hours=1)).isoformat()}')") == [
            (hour, 140, 2, True, 6.0),
            (hour + timedelta(hours=1), 140, 2, True, 6.0),
        ]
        assert runs(db)[-1][:4] == ("etl", "success", 22, 2)

    def test_rejected_readings_are_recorded(self, db, now, monkeypatch):
        good = fake_api(now.replace(minute=0))

        def one_bad_reading(path):
            data = good(path)
            if path.startswith("/intensity/"):
                data["data"][0]["intensity"] = {"forecast": None, "actual": None}
            return data
        monkeypatch.setattr(etl_job, "get_json", one_bad_reading)
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        job, status, inserted, _, rejected, message = runs(db)[-1]
        assert (status, rejected) == ("partial", 1) and "no intensity value" in message
        assert telemetry(db)[0][2] == 1  # that hour is built from its other half hour

    def test_database_failure_fails_the_run_and_is_logged(self, db, now, monkeypatch):
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        monkeypatch.setattr(etl_job, "upsert_rows", lambda conn, rows: 1 / 0)
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 1
        job, status, *_, message = runs(db)[-1]
        assert status == "failure" and "ZeroDivisionError" in message and "Traceback" in message

    def test_backfill_fetches_one_request_pair_per_day(self, db, now, monkeypatch):
        calls = []

        def api(path):
            calls.append(path)
            end = etl_job._parse_iso8601(path.split("/")[2])
            return fake_api(end)(path)
        monkeypatch.setattr(etl_job, "get_json", api)
        monkeypatch.setattr(etl_job.time, "sleep", lambda s: None)
        assert etl_job.run_pipeline(TEST_DATABASE_URL, days=3, now=now) == 0
        assert calls[:2] == ["/intensity/2026-09-24T13:00Z/pt24h", "/generation/2026-09-24T13:00Z/pt24h"]
        rows = telemetry(db)
        # Whole hours only: no hour is split across two requests.
        assert len(calls) == 6 and len(rows) == 72 and all(row[2] == 2 for row in rows)

    def test_a_row_is_never_replaced_by_one_with_fewer_half_hours(self, db, now, monkeypatch):
        etl_job.ensure_schema(db)
        hour = now.replace(minute=0)
        db.execute("INSERT INTO grid_telemetry (timestamp, overall_intensity, half_hours) VALUES (%s, 150, 2)", (hour,))
        monkeypatch.setattr(etl_job, "get_json", fake_api(hour + timedelta(minutes=30), actual=300))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        assert telemetry(db, f"timestamp = '{hour.isoformat()}'")[0][1:3] == (150, 2)


def fill_history(db, now, hours=100, skip=()):
    etl_job.ensure_schema(db)
    origin = now.replace(minute=0) - timedelta(hours=1)
    for h in range(hours):
        if h in skip:
            continue
        db.execute(
            "INSERT INTO grid_telemetry (timestamp, overall_intensity, fuel_wind_perc, fuel_solar_perc, fuel_gas_perc, "
            "fuel_nuclear_perc, half_hours) VALUES (%s, %s, 30, 5, 40, 15, 2)",
            (origin - timedelta(hours=h), 100 + h),
        )
    db.commit()
    return origin


class TestForecast:
    def test_stores_24_hours_for_each_metric_once(self, db, now):
        origin = fill_history(db, now)
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        rows = db.execute("SELECT fuel_type, prediction_timestamp, predicted_value, predicted_low, predicted_high "
                          "FROM grid_predictions WHERE fuel_type = 'Overall_Intensity' ORDER BY prediction_timestamp").fetchall()
        assert len(rows) == 24
        assert rows[0] == ("Overall_Intensity", origin + timedelta(hours=1), 100.0, 90.0, 110.0)
        assert db.execute("SELECT COUNT(*) FROM grid_predictions").fetchone()[0] == 24 * len(forecast.METRICS)

        # Same origin again: nothing new, and the model isn't even loaded.
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=None, model_id="fake") == 0
        assert db.execute("SELECT COUNT(*) FROM grid_predictions").fetchone()[0] == 24 * len(forecast.METRICS)

    def test_percentages_are_clamped(self, db, now):
        fill_history(db, now)
        db.execute("UPDATE grid_telemetry SET fuel_wind_perc = 95")
        db.commit()
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        assert db.execute("SELECT MAX(predicted_high) FROM grid_predictions WHERE fuel_type = 'Wind'").fetchone()[0] == 100

    def test_ignores_the_unfinished_hour_and_gaps(self, db, now):
        origin = fill_history(db, now, skip=(5, 6, 7))
        db.execute("INSERT INTO grid_telemetry (timestamp, overall_intensity, half_hours) VALUES (%s, 500, 1)",
                   (origin + timedelta(hours=1),))
        db.commit()
        got_origin, contexts = forecast.build_contexts(forecast.load_history(db, now), now)
        assert got_origin == origin
        series = contexts["Overall_Intensity"]
        assert len(series) == forecast.CONTEXT_HOURS and series[-1] == 100.0
        assert all(v != v for v in series[-8:-5])  # the gap is NaN

    def test_refuses_stale_or_thin_history(self, db, now):
        fill_history(db, now, hours=50)
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 1
        assert "need at least 72" in runs(db)[-1][-1]
        assert forecast.run(TEST_DATABASE_URL, now=now + timedelta(hours=5), pipeline=FakeModel(), model_id="fake") == 1
        assert "is the ETL running?" in runs(db)[-1][-1]

    def test_accuracy_views_score_forecasts_against_a_naive_baseline(self, db, now):
        origin = fill_history(db, now)
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        # The actuals arrive for the next two hours.
        for h, value in ((1, 110), (2, 80)):
            db.execute("INSERT INTO grid_telemetry (timestamp, overall_intensity, fuel_wind_perc, half_hours) "
                       "VALUES (%s, %s, 30, 2)", (origin + timedelta(hours=h), value))
        # An old Edge Function row is ignored.
        db.execute("INSERT INTO grid_predictions (prediction_timestamp, fuel_type, predicted_value) "
                   "VALUES (%s, 'Overall_Intensity', 42)", (origin + timedelta(hours=1),))
        db.commit()
        accuracy = db.execute("SELECT horizon_hours, actual_value, abs_error, within_interval, naive_value "
                              "FROM forecast_accuracy WHERE fuel_type = 'Overall_Intensity' ORDER BY 1").fetchall()
        assert [(float(h), a, e, w) for h, a, e, w, _ in accuracy] == [(1.0, 110, 10, True), (2.0, 80, 20, False)]
        assert accuracy[0][4] == 100 + 23  # the value 24 hours earlier
        skill = db.execute("SELECT forecasts, mean_abs_error, interval_coverage FROM forecast_skill "
                           "WHERE fuel_type = 'Overall_Intensity'").fetchone()
        assert skill == (2, 15, 0.5)


class TestBackfillResilience:
    def test_a_failing_day_is_skipped_and_the_rest_is_kept(self, db, now, monkeypatch):
        bad = etl_job.api_time(now.replace(minute=0) + timedelta(hours=1) - timedelta(days=1))

        def api(path):
            if bad in path:
                raise etl_job.requests.HTTPError("500 Server Error")
            return fake_api(etl_job._parse_iso8601(path.split("/")[2]))(path)
        monkeypatch.setattr(etl_job, "get_json", api)
        monkeypatch.setattr(etl_job.time, "sleep", lambda s: None)
        assert etl_job.run_pipeline(TEST_DATABASE_URL, days=3, now=now) == 1  # red, so it's noticed
        assert len(telemetry(db)) == 48  # days 1 and 3 were saved
        job, status, inserted, _, _, message = runs(db)[-1]
        assert (status, inserted) == ("partial", 48) and f"Skipped {bad}" in message

    def test_every_day_failing_is_a_failure(self, db, now, monkeypatch):
        def broken(path):
            raise etl_job.requests.ConnectionError("down")
        monkeypatch.setattr(etl_job, "get_json", broken)
        monkeypatch.setattr(etl_job.time, "sleep", lambda s: None)
        assert etl_job.run_pipeline(TEST_DATABASE_URL, days=2, now=now) == 1
        assert runs(db)[-1][1] == "failure" and telemetry(db) == []

    def test_rows_are_written_in_batches(self, db, now, monkeypatch):
        monkeypatch.setattr(etl_job, "UPSERT_BATCH", 5)
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        assert len(telemetry(db)) == 24 and runs(db)[-1][2] == 24
