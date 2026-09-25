"""Database tests against a real Postgres (set TEST_DATABASE_URL; CI runs one).
They start from the tables as they exist in the live database."""

from datetime import timedelta

import psycopg
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
        for view in ("forecast_accuracy", "forecast_skill", "dashboard_hourly"):
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


class TestLiveDatabaseCompatibility:
    """The live database had one-prediction-per-hour and dashboard views built
    on it (see LEGACY_SCHEMA); the forecast job failed on it in production."""

    def test_forecast_stores_even_where_old_edge_function_rows_exist(self, db, now):
        origin = fill_history(db, now)
        db.execute("INSERT INTO grid_predictions (prediction_timestamp, fuel_type, predicted_value) "
                   "VALUES (%s, 'Overall_Intensity', 42)", (origin + timedelta(hours=1),))
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        assert db.execute("SELECT COUNT(*) FROM grid_predictions WHERE model = 'fake'").fetchone()[0] == 120

    def test_forecasts_from_successive_runs_are_all_kept(self, db, now):
        fill_history(db, now)
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        # Three hours later the next forecast overlaps 21 of the same hours.
        fill_history(db, now + timedelta(hours=3), hours=3)
        assert forecast.run(TEST_DATABASE_URL, now=now + timedelta(hours=3), pipeline=FakeModel(), model_id="fake") == 0
        assert db.execute("SELECT COUNT(DISTINCT forecast_origin) FROM grid_predictions").fetchone()[0] == 2

    def test_the_looker_era_views_are_removed(self, db, now):
        # Things people built on the old views in Supabase, which go with them.
        db.execute("CREATE MATERIALIZED VIEW v_daily_accuracy AS SELECT * FROM actual_vs_predicted")
        db.execute("CREATE VIEW my_error_chart AS SELECT * FROM error_rate_24h")
        # Views that were made for Looker by hand in Supabase.
        db.execute("CREATE VIEW grid_telemetry_24h AS SELECT * FROM grid_telemetry")
        db.execute("CREATE VIEW grid_predictions_24h AS SELECT * FROM grid_predictions")
        db.execute("CREATE VIEW view_energy_mix_long AS SELECT timestamp, 'Wind' AS fuel, fuel_wind_perc AS perc FROM grid_telemetry")
        db.execute("CREATE VIEW my_own_view AS SELECT timestamp FROM grid_telemetry")  # unrelated: kept
        etl_job.ensure_schema(db)
        etl_job.ensure_schema(db)  # and again: nothing left to drop is fine
        remaining = {row[0] for row in db.execute(
            "SELECT relname FROM pg_class WHERE relkind IN ('v', 'm') AND relnamespace = 'public'::regnamespace")}
        for retired in ("grid_predictions_extended", "actual_vs_predicted", "actual_vs_predicted_24h",
                        "error_rate_24h", "latest_reading", "grid_telemetry_wide_last_24_hours",
                        "v_daily_accuracy", "my_error_chart", "grid_mix_hourly",
                        "grid_telemetry_24h", "grid_predictions_24h", "view_energy_mix_long"):
            assert retired not in remaining
        assert {"my_own_view", "forecast_accuracy", "forecast_skill", "dashboard_hourly"} <= remaining
        db.execute("DROP VIEW my_own_view")


def view_columns(db):
    """{view: [(column, type), ...]} for every view in the public schema."""
    columns = {}
    for view, column, data_type in db.execute(
        "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c "
        "JOIN information_schema.views v ON v.table_name = c.table_name AND v.table_schema = c.table_schema "
        "WHERE c.table_schema = 'public' ORDER BY c.table_name, c.ordinal_position"
    ):
        columns.setdefault(view, []).append((column, data_type))
    return columns


class TestViewStability:
    """The dashboard reads views by name and column. Upgrades may add views
    and add columns at the end, but never rename, retype or remove."""

    def test_existing_views_keep_every_column(self, db, now, monkeypatch):
        etl_job.ensure_schema(db)
        before = view_columns(db)
        assert "dashboard_hourly" in before and "forecast_skill" in before
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        after = view_columns(db)
        for view, columns in before.items():
            assert after[view][:len(columns)] == columns, view

    def test_every_view_can_be_queried_after_a_run(self, db, now, monkeypatch):
        fill_history(db, now)  # the forecast needs three days of history
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        for view in view_columns(db):
            db.execute(f"SELECT * FROM {view} LIMIT 5").fetchall()

    def test_a_hand_edited_view_does_not_stop_the_data(self, db, now, monkeypatch):
        # Someone changes a view in Supabase so ours can no longer replace it.
        db.execute("CREATE VIEW dashboard_pipeline AS SELECT 'x'::text AS run_timestamp")
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 1  # red, so it's noticed
        assert len(telemetry(db)) == 24  # but the data still loaded
        _, status, *_, message = runs(db)[-1]
        assert status == "partial" and "Dashboard views were not updated" in message
        assert db.execute("SELECT * FROM dashboard_pipeline").fetchone() == ("x",)  # left as it was


class TestPublicApi:
    """The dashboard reads Supabase with the public (anon) key, so that key
    must see the dashboard_* views and nothing else, and never write."""

    def as_anon(self, db, sql):
        db.execute("SET ROLE anon")
        try:
            return db.execute(sql).fetchall()
        finally:
            db.execute("RESET ROLE")

    def test_the_public_key_reads_only_the_dashboard_views(self, db, now, monkeypatch):
        fill_history(db, now)
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        for view in ("dashboard_hourly", "dashboard_daily", "dashboard_forecast",
                     "dashboard_forecast_skill", "dashboard_pipeline"):
            self.as_anon(db, f"SELECT * FROM {view} LIMIT 1")
        for private in ("grid_telemetry", "grid_predictions", "etl_runs", "forecast_accuracy", "forecast_skill"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                self.as_anon(db, f"SELECT * FROM {private} LIMIT 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            self.as_anon(db, "INSERT INTO grid_telemetry (timestamp) VALUES (NOW()) RETURNING id")
        assert db.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'grid_telemetry'").fetchone() == (True,)

    def test_views_serve_what_the_dashboard_draws(self, db, now, monkeypatch):
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(TEST_DATABASE_URL, now=now) == 0
        latest = db.execute("SELECT * FROM dashboard_hourly ORDER BY timestamp DESC LIMIT 1").fetchone()
        # timestamp, intensity, is_actual, wind, gas, nuclear, solar, imports, biomass, other
        assert latest[1:] == (150, True, 35.0, 30.0, 15.0, 5.0, 7.5, 6.0, 1.5)
        day = db.execute("SELECT intensity, wind, other, hours FROM dashboard_daily ORDER BY day DESC LIMIT 1").fetchone()
        assert day[0] == 150 and float(day[1]) == 35.0 and float(day[2]) == 1.5
        runs_seen = db.execute("SELECT job, status, rows_inserted FROM dashboard_pipeline").fetchall()
        assert runs_seen == [("etl", "success", 24)]

    def test_only_the_newest_forecast_is_served(self, db, now):
        fill_history(db, now)
        assert forecast.run(TEST_DATABASE_URL, now=now, pipeline=FakeModel(), model_id="fake") == 0
        fill_history(db, now + timedelta(hours=2), hours=2)
        assert forecast.run(TEST_DATABASE_URL, now=now + timedelta(hours=2), pipeline=FakeModel(), model_id="fake") == 0
        origins = db.execute("SELECT DISTINCT origin FROM dashboard_forecast").fetchall()
        assert origins == [(now.replace(minute=0) + timedelta(hours=1),)]
        assert db.execute("SELECT COUNT(*) FROM dashboard_forecast").fetchone()[0] == 120

    def test_row_level_security_does_not_block_a_table_owner(self, db, now, monkeypatch):
        """On Supabase the pipeline runs as the (non-superuser) table owner."""
        db.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_owner') "
                   "THEN CREATE ROLE etl_owner LOGIN PASSWORD 'etl_owner'; END IF; END $$")
        db.execute("GRANT CREATE, USAGE ON SCHEMA public TO etl_owner")
        for table in ("grid_telemetry", "grid_predictions", "etl_runs"):
            db.execute(f"ALTER TABLE {table} OWNER TO etl_owner")
        for view in ("grid_predictions_extended", "actual_vs_predicted", "actual_vs_predicted_24h",
                     "error_rate_24h", "latest_reading", "grid_telemetry_wide_last_24_hours"):
            db.execute(f"ALTER VIEW {view} OWNER TO etl_owner")
        owner_url = TEST_DATABASE_URL.replace("postgres:postgres@", "etl_owner:etl_owner@", 1)
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(owner_url, now=now) == 0
        assert etl_job.run_pipeline(owner_url, now=now) == 0  # a second run, with RLS now on
        assert db.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'grid_telemetry'").fetchone() == (True,)
        assert len(telemetry(db)) == 24 and [r[1] for r in runs(db)] == ["success", "success"]


def test_other_apps_tables_keep_their_permissions(db):
    """The permissions step only touches the pipeline's own tables and views."""
    db.execute("DROP TABLE IF EXISTS saved_itineraries")
    db.execute("CREATE TABLE saved_itineraries (id SERIAL PRIMARY KEY)")
    db.execute("GRANT SELECT ON saved_itineraries TO anon")
    db.execute("CREATE VIEW hand_made_accuracy AS SELECT * FROM grid_telemetry")  # a view made in Supabase
    etl_job.ensure_schema(db)
    db.execute("SET ROLE anon")
    try:
        db.execute("SELECT * FROM saved_itineraries").fetchall()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("SELECT * FROM hand_made_accuracy").fetchall()
    finally:
        db.execute("RESET ROLE")
        db.execute("DROP VIEW IF EXISTS hand_made_accuracy")
        db.execute("DROP TABLE saved_itineraries")
