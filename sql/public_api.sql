-- The read-only API behind the dashboard (dashboard/). Supabase exposes views
-- over its REST API; of this pipeline's data, these dashboard_* views are the
-- only things the public key can read. The raw tables, etl_runs with its error
-- messages and the older views are closed to it. Applied on every run.
--
-- Each dashboard view comes in two parts:
--   * dashboard_private.<name> does the work. It runs with its owner's
--     permissions, so it can read the closed tables. The schema is not one
--     Supabase's API exposes, so nobody can query it directly.
--   * public.dashboard_<name> just passes it on. It runs with the reader's
--     permissions (security_invoker), as Supabase's security advisor requires
--     of views the API exposes.
-- Never add dashboard_private to the API's exposed schemas.

CREATE SCHEMA IF NOT EXISTS dashboard_private;

CREATE OR REPLACE VIEW dashboard_private.hourly AS
SELECT
    timestamp,
    overall_intensity AS intensity,
    intensity_is_actual AS is_actual,
    fuel_wind_perc AS wind,
    fuel_gas_perc AS gas,
    fuel_nuclear_perc AS nuclear,
    fuel_solar_perc AS solar,
    fuel_imports_perc AS imports,
    fuel_biomass_perc AS biomass,
    -- hydro, coal and "other" are small; the dashboard shows them together
    CASE WHEN COALESCE(fuel_hydro_perc, fuel_coal_perc, fuel_other_perc) IS NOT NULL
         THEN COALESCE(fuel_hydro_perc, 0) + COALESCE(fuel_coal_perc, 0) + COALESCE(fuel_other_perc, 0)
    END AS other
FROM public.grid_telemetry
WHERE EXTRACT(MINUTE FROM timestamp) = 0 AND overall_intensity IS NOT NULL;

-- Days in UK time, for the long view.
CREATE OR REPLACE VIEW dashboard_private.daily AS
SELECT
    (timestamp AT TIME ZONE 'Europe/London')::date AS day,
    ROUND(AVG(overall_intensity))::int AS intensity,
    MIN(overall_intensity) AS intensity_min,
    MAX(overall_intensity) AS intensity_max,
    ROUND(AVG(fuel_wind_perc)::numeric, 1) AS wind,
    ROUND(AVG(fuel_gas_perc)::numeric, 1) AS gas,
    ROUND(AVG(fuel_nuclear_perc)::numeric, 1) AS nuclear,
    ROUND(AVG(fuel_solar_perc)::numeric, 1) AS solar,
    ROUND(AVG(fuel_imports_perc)::numeric, 1) AS imports,
    ROUND(AVG(fuel_biomass_perc)::numeric, 1) AS biomass,
    ROUND(AVG(COALESCE(fuel_hydro_perc, 0) + COALESCE(fuel_coal_perc, 0) + COALESCE(fuel_other_perc, 0))
          FILTER (WHERE COALESCE(fuel_hydro_perc, fuel_coal_perc, fuel_other_perc) IS NOT NULL)::numeric, 1) AS other,
    COUNT(*) AS hours
FROM public.grid_telemetry
WHERE EXTRACT(MINUTE FROM timestamp) = 0 AND overall_intensity IS NOT NULL
GROUP BY 1;

-- The newest forecast (all metrics, 24 hours ahead).
CREATE OR REPLACE VIEW dashboard_private.forecast AS
SELECT
    prediction_timestamp AS timestamp,
    fuel_type AS metric,
    predicted_value AS value,
    predicted_low AS low,
    predicted_high AS high,
    forecast_origin AS origin,
    model
FROM public.grid_predictions
WHERE model IS NOT NULL
  AND forecast_origin = (SELECT MAX(forecast_origin) FROM public.grid_predictions WHERE model IS NOT NULL);

CREATE OR REPLACE VIEW dashboard_private.forecast_skill AS
SELECT model, fuel_type AS metric, forecasts, mean_abs_error, naive_mean_abs_error, skill, interval_coverage
FROM public.forecast_skill;

-- Pipeline health without error messages (those can contain internals).
CREATE OR REPLACE VIEW dashboard_private.pipeline AS
SELECT run_timestamp, COALESCE(job, 'etl') AS job, status, rows_inserted, rows_updated, rows_rejected, execution_time_ms
FROM public.etl_runs
WHERE run_timestamp > NOW() - INTERVAL '14 days';

CREATE OR REPLACE VIEW dashboard_hourly WITH (security_invoker = true) AS SELECT * FROM dashboard_private.hourly;
CREATE OR REPLACE VIEW dashboard_daily WITH (security_invoker = true) AS SELECT * FROM dashboard_private.daily;
CREATE OR REPLACE VIEW dashboard_forecast WITH (security_invoker = true) AS SELECT * FROM dashboard_private.forecast;
CREATE OR REPLACE VIEW dashboard_forecast_skill WITH (security_invoker = true) AS SELECT * FROM dashboard_private.forecast_skill;
CREATE OR REPLACE VIEW dashboard_pipeline WITH (security_invoker = true) AS SELECT * FROM dashboard_private.pipeline;

-- Permissions. The anon and authenticated roles only exist on Supabase.
DO $$
DECLARE
    item record;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        RETURN;
    END IF;

    -- Close the pipeline's tables, and every view built on them in the public
    -- schema (however many layers deep, including any made by hand), to the
    -- API roles; then open the dashboard views. Other apps' tables in the same
    -- project are untouched.
    FOR item IN
        WITH RECURSIVE pipeline AS (
            SELECT c.oid FROM pg_class c
            WHERE c.oid IN ('public.grid_telemetry'::regclass, 'public.grid_predictions'::regclass, 'public.etl_runs'::regclass)
            UNION
            SELECT r.ev_class
            FROM pg_depend d
            JOIN pg_rewrite r ON r.oid = d.objid
            JOIN pipeline p ON d.refobjid = p.oid
            WHERE d.classid = 'pg_rewrite'::regclass AND r.ev_class <> p.oid
        )
        SELECT c.relname FROM pg_class c JOIN pipeline p ON p.oid = c.oid
        WHERE c.relnamespace = 'public'::regnamespace AND c.relname NOT LIKE 'dashboard\_%'
    LOOP
        EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', item.relname);
    END LOOP;
    GRANT SELECT ON dashboard_hourly, dashboard_daily, dashboard_forecast,
                    dashboard_forecast_skill, dashboard_pipeline TO anon, authenticated;

    -- The public views read the private ones as the reader, so the API roles
    -- may read those five (and nothing else in the schema); only through the
    -- public views, since the API doesn't serve this schema.
    REVOKE ALL ON SCHEMA dashboard_private FROM PUBLIC;
    GRANT USAGE ON SCHEMA dashboard_private TO anon, authenticated;
    REVOKE ALL ON ALL TABLES IN SCHEMA dashboard_private FROM anon, authenticated;
    GRANT SELECT ON dashboard_private.hourly, dashboard_private.daily, dashboard_private.forecast,
                    dashboard_private.forecast_skill, dashboard_private.pipeline TO anon, authenticated;

    -- Row-level security as a second lock on the raw tables, with a policy
    -- that says so outright: the API roles see nothing (it's restrictive, so
    -- no policy added later can widen it). Only switched on when the role
    -- running this owns the tables or bypasses RLS, so it can never block the
    -- pipeline or the private views, which read as that role.
    IF (SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user)
       OR (SELECT bool_and(pg_has_role(current_user, c.relowner, 'USAGE'))
           FROM pg_class c WHERE c.oid IN ('public.grid_telemetry'::regclass, 'public.grid_predictions'::regclass, 'public.etl_runs'::regclass)) THEN
        FOR item IN SELECT unnest(ARRAY['grid_telemetry', 'grid_predictions', 'etl_runs']) AS relname LOOP
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', item.relname);
            EXECUTE format('DROP POLICY IF EXISTS "No public access" ON public.%I', item.relname);
            EXECUTE format('CREATE POLICY "No public access" ON public.%I AS RESTRICTIVE FOR ALL '
                           'TO anon, authenticated USING (false) WITH CHECK (false)', item.relname);
        END LOOP;
    ELSE
        RAISE NOTICE 'Row-level security left off: % does not own the tables', current_user;
    END IF;

    NOTIFY pgrst, 'reload schema';  -- let the Supabase API see new views at once
END $$;
