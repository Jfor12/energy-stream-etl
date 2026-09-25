-- Forecast evaluation views (the dashboard reads forecast_skill through
-- dashboard_forecast_skill). Applied after schema.sql on every run.

-- Every model forecast next to what actually happened. The naive baseline
-- repeats the value from 24 hours before the forecast hour, which was always
-- known when the forecast was made (the horizon is at most 24 hours).
CREATE OR REPLACE VIEW forecast_accuracy AS
WITH actuals AS (
    SELECT timestamp, 'Overall_Intensity' AS fuel_type, overall_intensity::DOUBLE PRECISION AS value FROM grid_telemetry
    UNION ALL SELECT timestamp, 'Gas', fuel_gas_perc FROM grid_telemetry
    UNION ALL SELECT timestamp, 'Nuclear', fuel_nuclear_perc FROM grid_telemetry
    UNION ALL SELECT timestamp, 'Wind', fuel_wind_perc FROM grid_telemetry
    UNION ALL SELECT timestamp, 'Solar', fuel_solar_perc FROM grid_telemetry
)
SELECT
    p.model,
    p.fuel_type,
    p.forecast_origin,
    p.prediction_timestamp,
    EXTRACT(EPOCH FROM p.prediction_timestamp - p.forecast_origin) / 3600 AS horizon_hours,
    p.predicted_value,
    p.predicted_low,
    p.predicted_high,
    a.value AS actual_value,
    ABS(p.predicted_value - a.value) AS abs_error,
    a.value BETWEEN p.predicted_low AND p.predicted_high AS within_interval,
    naive.value AS naive_value,
    ABS(naive.value - a.value) AS naive_abs_error
FROM grid_predictions p
JOIN actuals a ON a.timestamp = p.prediction_timestamp AND a.fuel_type = p.fuel_type
LEFT JOIN actuals naive ON naive.timestamp = p.prediction_timestamp - INTERVAL '24 hours' AND naive.fuel_type = p.fuel_type
WHERE p.model IS NOT NULL AND a.value IS NOT NULL;

-- One line per model and metric: is the model better than the naive guess?
-- skill > 0 means it is; 0.2 means 20% lower average error than the baseline.
CREATE OR REPLACE VIEW forecast_skill AS
SELECT
    model,
    fuel_type,
    COUNT(*) AS forecasts,
    ROUND(AVG(abs_error)::NUMERIC, 2) AS mean_abs_error,
    ROUND(AVG(naive_abs_error)::NUMERIC, 2) AS naive_mean_abs_error,
    ROUND((1 - AVG(abs_error) / NULLIF(AVG(naive_abs_error), 0))::NUMERIC, 3) AS skill,
    ROUND(AVG(within_interval::INT)::NUMERIC, 3) AS interval_coverage
FROM forecast_accuracy
WHERE naive_abs_error IS NOT NULL
GROUP BY model, fuel_type;
