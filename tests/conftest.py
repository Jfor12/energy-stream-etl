import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

# The live database as it was before this version (tables, indexes and the
# dashboard views, as exported from Supabase), so the tests prove the schema
# upgrade and sql/dashboard_views.sql work on it.
LEGACY_SCHEMA = """
DROP TABLE IF EXISTS grid_telemetry, etl_runs, grid_predictions CASCADE;
CREATE TABLE grid_telemetry (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    overall_intensity INT,
    fuel_gas_perc DOUBLE PRECISION,
    fuel_nuclear_perc DOUBLE PRECISION,
    fuel_wind_perc DOUBLE PRECISION,
    fuel_solar_perc DOUBLE PRECISION
);
CREATE INDEX idx_telemetry_timestamp ON grid_telemetry(timestamp);
CREATE INDEX idx_telemetry_hour_utc ON grid_telemetry (date_trunc('hour', timestamp AT TIME ZONE 'UTC'));
CREATE TABLE grid_predictions (
    id BIGSERIAL PRIMARY KEY,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    fuel_type VARCHAR(20) NOT NULL,
    predicted_value DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_prediction_per_hour UNIQUE (prediction_timestamp, fuel_type)
);
CREATE INDEX idx_predictions_fuel_type ON grid_predictions(fuel_type);
-- The live database has the same rule a second time, as a plain unique index.
CREATE UNIQUE INDEX unique_prediction_fuel ON grid_predictions (prediction_timestamp, fuel_type);
CREATE TABLE etl_runs (
    id BIGSERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20),
    rows_inserted INT,
    execution_time_ms INT,
    error_message TEXT
);

CREATE VIEW grid_predictions_extended AS
WITH base_predictions AS (
    SELECT prediction_timestamp, fuel_type, predicted_value
    FROM grid_predictions
    WHERE fuel_type != 'Overall_Intensity'
),
other_fuel AS (
    SELECT prediction_timestamp, 'Other' AS fuel_type, (100.0 - SUM(predicted_value)) AS predicted_value
    FROM base_predictions
    GROUP BY prediction_timestamp
)
SELECT id, prediction_timestamp, fuel_type, predicted_value, created_at FROM grid_predictions
UNION ALL
SELECT NULL, prediction_timestamp, fuel_type, predicted_value, NOW() FROM other_fuel;

CREATE VIEW actual_vs_predicted AS
SELECT
    g.timestamp AS actual_timestamp,
    p.prediction_timestamp,
    p.fuel_type,
    CASE
        WHEN p.fuel_type = 'Overall_Intensity' THEN g.overall_intensity
        WHEN p.fuel_type = 'Wind' THEN g.fuel_wind_perc
        WHEN p.fuel_type = 'Solar' THEN g.fuel_solar_perc
        WHEN p.fuel_type = 'Gas' THEN g.fuel_gas_perc
        WHEN p.fuel_type = 'Nuclear' THEN g.fuel_nuclear_perc
        WHEN p.fuel_type = 'Other' THEN (100.0 - (COALESCE(g.fuel_wind_perc,0) + COALESCE(g.fuel_solar_perc,0) + COALESCE(g.fuel_gas_perc,0) + COALESCE(g.fuel_nuclear_perc,0)))
        ELSE NULL
    END AS actual_value,
    p.predicted_value,
    ABS(
        (CASE
            WHEN p.fuel_type = 'Overall_Intensity' THEN g.overall_intensity
            WHEN p.fuel_type = 'Wind' THEN g.fuel_wind_perc
            WHEN p.fuel_type = 'Solar' THEN g.fuel_solar_perc
            WHEN p.fuel_type = 'Gas' THEN g.fuel_gas_perc
            WHEN p.fuel_type = 'Nuclear' THEN g.fuel_nuclear_perc
            WHEN p.fuel_type = 'Other' THEN (100.0 - (COALESCE(g.fuel_wind_perc,0) + COALESCE(g.fuel_solar_perc,0) + COALESCE(g.fuel_gas_perc,0) + COALESCE(g.fuel_nuclear_perc,0)))
            ELSE NULL
        END) - p.predicted_value
    ) AS prediction_error
FROM grid_telemetry g
INNER JOIN grid_predictions_extended p ON g.timestamp = p.prediction_timestamp;

CREATE VIEW actual_vs_predicted_24h AS
SELECT *, (100.0 * prediction_error / NULLIF(actual_value, 0))::NUMERIC(10,2) AS error_percentage
FROM actual_vs_predicted
WHERE actual_timestamp >= NOW() - INTERVAL '24 hours';

CREATE VIEW error_rate_24h AS
SELECT
    date_trunc('hour', actual_timestamp AT TIME ZONE 'UTC') AS hour_utc,
    fuel_type,
    AVG(100.0 * prediction_error / NULLIF(actual_value, 0))::NUMERIC(10,2) AS avg_error_percentage,
    COUNT(*) AS n_predictions
FROM actual_vs_predicted
WHERE actual_timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY 1, 2;

CREATE VIEW latest_reading AS
SELECT * FROM grid_telemetry ORDER BY timestamp DESC LIMIT 1;

CREATE VIEW grid_telemetry_wide_last_24_hours AS
SELECT * FROM grid_telemetry WHERE timestamp >= NOW() - INTERVAL '24 hours';
"""

MIX = {"gas": 30.0, "coal": 0.0, "nuclear": 15.0, "wind": 35.0, "solar": 5.0,
       "hydro": 1.0, "biomass": 6.0, "imports": 7.5, "other": 0.5}


def half_hour(start: datetime) -> dict:
    return {"from": start.strftime("%Y-%m-%dT%H:%MZ"), "to": (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%MZ")}


def intensity_entry(start, actual=150, forecast=160, index="moderate"):
    return {**half_hour(start), "intensity": {"forecast": forecast, "actual": actual, "index": index}}


def generation_entry(start, mix=None):
    mix = MIX if mix is None else mix
    return {**half_hour(start), "generationmix": [{"fuel": fuel, "perc": perc} for fuel, perc in mix.items()]}


def fake_api(end: datetime, hours: int = 24, **intensity_kwargs):
    """A stand-in for etl_job.get_json covering `hours` before `end`."""
    starts = [end - timedelta(minutes=30 * (i + 1)) for i in range(hours * 2)][::-1]

    def get_json(path):
        if path.startswith("/intensity/"):
            return {"data": [intensity_entry(s, **intensity_kwargs) for s in starts]}
        if path.startswith("/generation/"):
            return {"data": [generation_entry(s) for s in starts]}
        raise AssertionError(f"unexpected path {path}")
    return get_json


class FakeModel:
    """Stands in for Chronos: predicts the last value, +-10%."""
    class Result(list):
        def tolist(self):
            return list(self)

    def predict_quantiles(self, inputs, prediction_length, quantile_levels):
        last = [[v for v in series if v == v][-1] for series in inputs]
        return self.Result([[(v * 0.9, v, v * 1.1)] * prediction_length for v in last]), None


@pytest.fixture
def db():
    """A connection to a scratch database holding the legacy tables."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    import etl_job
    with etl_job.connect(TEST_DATABASE_URL) as conn:
        # Autocommit, so reads here don't hold locks the code under test waits for.
        conn.autocommit = True
        conn.execute(LEGACY_SCHEMA)
        yield conn


@pytest.fixture
def now():
    return datetime(2026, 9, 24, 12, 10, tzinfo=timezone.utc)
