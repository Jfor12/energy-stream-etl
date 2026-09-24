-- Analytics views for Looker Studio. Applied after schema.sql on every run.

-- The hourly mix with every fuel, plus the groupings the dashboard uses.
-- coverage_perc should be close to 100; hours stored before all fuels were
-- collected (before this change) show only gas, nuclear, wind and solar.
CREATE OR REPLACE VIEW grid_mix_hourly AS
SELECT
    timestamp,
    overall_intensity,
    intensity_forecast,
    intensity_is_actual,
    fuel_gas_perc,
    fuel_coal_perc,
    fuel_nuclear_perc,
    fuel_wind_perc,
    fuel_solar_perc,
    fuel_hydro_perc,
    fuel_biomass_perc,
    fuel_imports_perc,
    fuel_other_perc,
    COALESCE(fuel_wind_perc, 0) + COALESCE(fuel_solar_perc, 0) + COALESCE(fuel_hydro_perc, 0) AS renewables_perc,
    COALESCE(fuel_gas_perc, 0) + COALESCE(fuel_coal_perc, 0) AS fossil_perc,
    COALESCE(fuel_gas_perc, 0) + COALESCE(fuel_coal_perc, 0) + COALESCE(fuel_nuclear_perc, 0)
        + COALESCE(fuel_wind_perc, 0) + COALESCE(fuel_solar_perc, 0) + COALESCE(fuel_hydro_perc, 0)
        + COALESCE(fuel_biomass_perc, 0) + COALESCE(fuel_imports_perc, 0) + COALESCE(fuel_other_perc, 0) AS coverage_perc
FROM grid_telemetry;

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
