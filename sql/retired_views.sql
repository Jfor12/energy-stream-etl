-- Views from the earlier Looker Studio report and the January 2026 scripts,
-- replaced by the dashboard (dashboard/ and sql/public_api.sql). Their
-- definitions are in the git history (sql/dashboard_views.sql, removed with
-- this file's first version). Anything built on top of them goes too.
-- Safe to run every time: names that no longer exist are skipped.
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT c.relname, c.relkind
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm') AND c.relname IN (
            'error_rate_24h', 'actual_vs_predicted_24h', 'actual_vs_predicted', 'grid_predictions_extended',
            'latest_reading', 'grid_telemetry_wide_last_24_hours', 'view_daily_cleanliness', 'grid_mix_hourly',
            'v_daily_accuracy', 'v_hourly_accuracy', 'v_weekly_accuracy')
    LOOP
        -- An earlier iteration's CASCADE may already have removed it.
        IF to_regclass(format('public.%I', item.relname)) IS NOT NULL THEN
            EXECUTE format('DROP %s IF EXISTS public.%I CASCADE',
                           CASE item.relkind WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'VIEW' END, item.relname);
            RAISE NOTICE 'Removed retired view %', item.relname;
        END IF;
    END LOOP;
END $$;
