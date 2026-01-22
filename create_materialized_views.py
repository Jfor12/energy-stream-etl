#!/usr/bin/env python3
"""
Create materialized views for Looker dashboard with optimal performance.
These views pre-aggregate accuracy data for fast queries.
"""

import psycopg

DB_URL = 'postgresql://postgres.unrhldictkhzmbtyiuti:romano10romano20@aws-1-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require'

SQL = """
-- 1. Daily accuracy summary (much smaller dataset)
DROP MATERIALIZED VIEW IF EXISTS v_daily_accuracy CASCADE;

CREATE MATERIALIZED VIEW v_daily_accuracy AS
SELECT 
  DATE(prediction_created_at) as forecast_date,
  fuel_type,
  COUNT(*) as total_predictions,
  ROUND(AVG(error_percentage), 2) as avg_error_pct,
  ROUND(MAX(error_percentage), 2) as worst_error_pct,
  ROUND(STDDEV(error_percentage), 2) as error_std_dev
FROM actual_vs_predicted
WHERE actual_value IS NOT NULL
GROUP BY DATE(prediction_created_at), fuel_type;

CREATE INDEX idx_daily_accuracy_date ON v_daily_accuracy(forecast_date DESC, fuel_type);

-- 2. Hourly performance snapshot
DROP MATERIALIZED VIEW IF EXISTS v_hourly_accuracy CASCADE;

CREATE MATERIALIZED VIEW v_hourly_accuracy AS
SELECT 
  DATE_TRUNC('hour', prediction_created_at) as forecast_hour,
  fuel_type,
  COUNT(*) as predictions,
  ROUND(AVG(error_percentage), 2) as avg_error_pct
FROM actual_vs_predicted
WHERE actual_value IS NOT NULL
GROUP BY DATE_TRUNC('hour', prediction_created_at), fuel_type;

CREATE INDEX idx_hourly_accuracy_hour ON v_hourly_accuracy(forecast_hour DESC, fuel_type);

-- 3. Weekly trends (for high-level dashboard)
DROP MATERIALIZED VIEW IF EXISTS v_weekly_accuracy CASCADE;

CREATE MATERIALIZED VIEW v_weekly_accuracy AS
SELECT 
  DATE_TRUNC('week', prediction_created_at) as week_start,
  fuel_type,
  ROUND(AVG(error_percentage), 2) as avg_error_pct,
  COUNT(*) as total_predictions
FROM actual_vs_predicted
WHERE actual_value IS NOT NULL
GROUP BY DATE_TRUNC('week', prediction_created_at), fuel_type;

CREATE INDEX idx_weekly_accuracy_week ON v_weekly_accuracy(week_start DESC, fuel_type);

-- Grant public access for Looker
GRANT SELECT ON v_daily_accuracy TO anon;
GRANT SELECT ON v_daily_accuracy TO authenticated;

GRANT SELECT ON v_hourly_accuracy TO anon;
GRANT SELECT ON v_hourly_accuracy TO authenticated;

GRANT SELECT ON v_weekly_accuracy TO anon;
GRANT SELECT ON v_weekly_accuracy TO authenticated;
"""

try:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            print("🔄 Creating materialized views...\n")
            cur.execute(SQL)
            conn.commit()
            print("✅ All materialized views created successfully!\n")
            
            # Show statistics for each view
            views = [
                ('v_daily_accuracy', 'Daily Accuracy Summary'),
                ('v_hourly_accuracy', 'Hourly Performance'),
                ('v_weekly_accuracy', 'Weekly Trends')
            ]
            
            for view_name, description in views:
                cur.execute(f"SELECT COUNT(*) as row_count FROM {view_name};")
                count = cur.fetchone()[0]
                print(f"📊 {description} ({view_name})")
                print(f"   Rows: {count:,}")
                
                cur.execute(f"SELECT * FROM {view_name} LIMIT 3;")
                cols = [desc[0] for desc in cur.description]
                print(f"   Columns: {', '.join(cols)}")
                print()
            
            # Show sample data
            print("=" * 70)
            print("📈 Sample Data from v_daily_accuracy (for Looker dashboard):")
            print("=" * 70)
            cur.execute("""
                SELECT 
                    forecast_date, 
                    fuel_type, 
                    total_predictions, 
                    avg_error_pct, 
                    worst_error_pct
                FROM v_daily_accuracy
                ORDER BY forecast_date DESC
                LIMIT 10;
            """)
            for row in cur.fetchall():
                date_str = str(row[0]) if hasattr(row[0], '__str__') else row[0]
                print(f"{date_str} | {row[1]:15} | Predictions: {row[2]:4} | Avg Error: {row[3]:6}% | Max Error: {row[4]:6}%")
            
            print("\n" + "=" * 70)
            print("✨ Ready for Looker! These views are optimised for fast queries.")
            print("=" * 70)
                
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
