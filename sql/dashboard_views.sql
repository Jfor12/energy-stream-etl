-- The views the Looker Studio dashboard was built on, as they were in
-- Supabase, with one change: predictions now come from the forecast job, and
-- only the newest real forecast for each hour is used (rows with no model,
-- from the old Edge Function, are ignored). Column names and types are
-- unchanged, so CREATE OR REPLACE keeps the dashboard working.
-- Applied on every run; edit the views here rather than in Supabase.

CREATE OR REPLACE VIEW grid_predictions_extended AS
WITH latest AS (
    SELECT DISTINCT ON (prediction_timestamp, fuel_type)
        id, prediction_timestamp, fuel_type, predicted_value, created_at
    FROM grid_predictions
    WHERE model IS NOT NULL
    ORDER BY prediction_timestamp, fuel_type, forecast_origin DESC
),
base_predictions AS (
    SELECT prediction_timestamp, fuel_type, predicted_value
    FROM latest
    WHERE fuel_type != 'Overall_Intensity'
),
other_fuel AS (
    -- "Other": whatever the four forecast fuels leave of 100%.
    SELECT prediction_timestamp, 'Other' AS fuel_type, (100.0 - SUM(predicted_value)) AS predicted_value
    FROM base_predictions
    GROUP BY prediction_timestamp
)
SELECT id, prediction_timestamp, fuel_type, predicted_value, created_at FROM latest
UNION ALL
SELECT NULL, prediction_timestamp, fuel_type, predicted_value, NOW() FROM other_fuel;

CREATE OR REPLACE VIEW actual_vs_predicted AS
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

CREATE OR REPLACE VIEW actual_vs_predicted_24h AS
SELECT *, (100.0 * prediction_error / NULLIF(actual_value, 0))::NUMERIC(10,2) AS error_percentage
FROM actual_vs_predicted
WHERE actual_timestamp >= NOW() - INTERVAL '24 hours';

CREATE OR REPLACE VIEW error_rate_24h AS
SELECT
    date_trunc('hour', actual_timestamp AT TIME ZONE 'UTC') AS hour_utc,
    fuel_type,
    AVG(100.0 * prediction_error / NULLIF(actual_value, 0))::NUMERIC(10,2) AS avg_error_percentage,
    COUNT(*) AS n_predictions
FROM actual_vs_predicted
WHERE actual_timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY 1, 2;

-- SELECT * is expanded when a view is created, so recreating these picks up
-- the columns added since (all fuels, intensity_forecast, half_hours, ...).
CREATE OR REPLACE VIEW latest_reading AS
SELECT * FROM grid_telemetry ORDER BY timestamp DESC LIMIT 1;

CREATE OR REPLACE VIEW grid_telemetry_wide_last_24_hours AS
SELECT * FROM grid_telemetry WHERE timestamp >= NOW() - INTERVAL '24 hours';
