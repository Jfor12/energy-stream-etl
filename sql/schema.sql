-- Schema for the grid pipeline. Safe to run repeatedly: etl_job.py and
-- forecast.py apply it at the start of every run. Existing columns are never
-- renamed or dropped, so views and dashboards built on them keep working.

-- One row per hour: the average of the two half-hourly readings in that hour.
CREATE TABLE IF NOT EXISTS grid_telemetry (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ,
    overall_intensity INT,
    fuel_gas_perc DOUBLE PRECISION,
    fuel_nuclear_perc DOUBLE PRECISION,
    fuel_wind_perc DOUBLE PRECISION,
    fuel_solar_perc DOUBLE PRECISION
);

ALTER TABLE grid_telemetry
    ADD COLUMN IF NOT EXISTS fuel_biomass_perc DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fuel_coal_perc DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fuel_imports_perc DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fuel_hydro_perc DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS fuel_other_perc DOUBLE PRECISION,
    -- National Grid's own forecast for the hour, kept alongside the reading.
    ADD COLUMN IF NOT EXISTS intensity_forecast INT,
    -- True when overall_intensity is a measured value for every half hour,
    -- false when at least one half hour only had a forecast so far.
    ADD COLUMN IF NOT EXISTS intensity_is_actual BOOLEAN,
    -- How many of the hour's two half-hourly readings the row is built from.
    ADD COLUMN IF NOT EXISTS half_hours SMALLINT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS grid_telemetry_timestamp_key ON grid_telemetry (timestamp);

CREATE TABLE IF NOT EXISTS etl_runs (
    id BIGSERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20),
    rows_inserted INT,
    execution_time_ms INT,
    error_message TEXT
);

ALTER TABLE etl_runs
    ADD COLUMN IF NOT EXISTS job VARCHAR(20),
    ADD COLUMN IF NOT EXISTS rows_updated INT,
    ADD COLUMN IF NOT EXISTS rows_rejected INT;

CREATE TABLE IF NOT EXISTS grid_predictions (
    id BIGSERIAL PRIMARY KEY,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    fuel_type VARCHAR NOT NULL,
    predicted_value DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE grid_predictions
    -- Rows without a model came from the old Edge Function (see README).
    ADD COLUMN IF NOT EXISTS model VARCHAR,
    -- The last observed hour the forecast was made from.
    ADD COLUMN IF NOT EXISTS forecast_origin TIMESTAMPTZ,
    -- 10th and 90th percentiles: an 80% prediction interval.
    ADD COLUMN IF NOT EXISTS predicted_low DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS predicted_high DOUBLE PRECISION;

-- The old Edge Function allowed one prediction per hour and fuel. Forecasts
-- are now kept from every run (to score them by horizon), so that rule goes;
-- the key below stops a run being stored twice instead.
ALTER TABLE grid_predictions DROP CONSTRAINT IF EXISTS unique_prediction_per_hour;
ALTER TABLE grid_predictions DROP CONSTRAINT IF EXISTS unique_prediction_per_fuel;
DROP INDEX IF EXISTS unique_prediction_per_hour;
DROP INDEX IF EXISTS unique_prediction_per_fuel;

CREATE UNIQUE INDEX IF NOT EXISTS grid_predictions_forecast_key
    ON grid_predictions (model, fuel_type, forecast_origin, prediction_timestamp)
    WHERE model IS NOT NULL;
