import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

# The tables as they exist in the live database before this version, so the
# tests prove the schema upgrade works on them.
LEGACY_SCHEMA = """
DROP VIEW IF EXISTS forecast_skill, forecast_accuracy, grid_mix_hourly;
DROP TABLE IF EXISTS grid_telemetry, etl_runs, grid_predictions;
CREATE TABLE grid_telemetry (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ,
    overall_intensity INT,
    fuel_gas_perc DOUBLE PRECISION,
    fuel_nuclear_perc DOUBLE PRECISION,
    fuel_wind_perc DOUBLE PRECISION,
    fuel_solar_perc DOUBLE PRECISION
);
CREATE TABLE etl_runs (
    id BIGSERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20),
    rows_inserted INT,
    execution_time_ms INT,
    error_message TEXT
);
CREATE TABLE grid_predictions (
    id BIGSERIAL PRIMARY KEY,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    fuel_type VARCHAR NOT NULL,
    predicted_value DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ
);
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
