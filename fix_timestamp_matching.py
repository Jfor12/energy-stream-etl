#!/usr/bin/env python3
"""
Create improved actual_vs_predicted view that properly matches telemetry to predictions
by normalizing timestamps to hourly boundaries.
"""

import psycopg

DB_URL = 'postgresql://postgres.unrhldictkhzmbtyiuti:romano10romano20@aws-1-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require'

SQL = """
-- Drop old view if exists
DROP VIEW IF EXISTS actual_vs_predicted CASCADE;

-- Create improved view with hourly timestamp matching
CREATE OR REPLACE VIEW actual_vs_predicted AS
SELECT 
  DATE_TRUNC('hour', t.timestamp) AS actual_timestamp,
  DATE_TRUNC('hour', p.created_at) AS prediction_created_at,
  p.fuel_type,
  
  -- Get actual value based on fuel_type
  CASE 
    WHEN p.fuel_type = 'Overall_Intensity' THEN t.overall_intensity
    WHEN p.fuel_type = 'Wind' THEN t.fuel_wind_perc
    WHEN p.fuel_type = 'Solar' THEN t.fuel_solar_perc
    WHEN p.fuel_type = 'Gas' THEN t.fuel_gas_perc
    WHEN p.fuel_type = 'Nuclear' THEN t.fuel_nuclear_perc
    ELSE NULL
  END AS actual_value,
  
  p.predicted_value,
  
  -- Calculate errors
  CASE 
    WHEN p.fuel_type = 'Overall_Intensity' THEN ABS(t.overall_intensity - p.predicted_value)
    WHEN p.fuel_type = 'Wind' THEN ABS(t.fuel_wind_perc - p.predicted_value)
    WHEN p.fuel_type = 'Solar' THEN ABS(t.fuel_solar_perc - p.predicted_value)
    WHEN p.fuel_type = 'Gas' THEN ABS(t.fuel_gas_perc - p.predicted_value)
    WHEN p.fuel_type = 'Nuclear' THEN ABS(t.fuel_nuclear_perc - p.predicted_value)
    ELSE NULL
  END AS prediction_error,
  
  -- Error percentage
  CASE 
    WHEN p.fuel_type = 'Overall_Intensity' THEN 
      ROUND(CAST(ABS(t.overall_intensity - p.predicted_value) * 100.0 / NULLIF(t.overall_intensity, 0) AS NUMERIC(5,2)), 2)
    WHEN p.fuel_type IN ('Wind', 'Solar', 'Gas', 'Nuclear') THEN 
      ROUND(CAST(ABS(
        CASE 
          WHEN p.fuel_type = 'Wind' THEN t.fuel_wind_perc
          WHEN p.fuel_type = 'Solar' THEN t.fuel_solar_perc
          WHEN p.fuel_type = 'Gas' THEN t.fuel_gas_perc
          WHEN p.fuel_type = 'Nuclear' THEN t.fuel_nuclear_perc
        END - p.predicted_value) * 100.0 / NULLIF(
        CASE 
          WHEN p.fuel_type = 'Wind' THEN t.fuel_wind_perc
          WHEN p.fuel_type = 'Solar' THEN t.fuel_solar_perc
          WHEN p.fuel_type = 'Gas' THEN t.fuel_gas_perc
          WHEN p.fuel_type = 'Nuclear' THEN t.fuel_nuclear_perc
        END, 0) AS NUMERIC(5,2)), 2)
    ELSE NULL
  END AS error_percentage
  
FROM grid_predictions p
INNER JOIN grid_telemetry t 
  -- Match by hour: telemetry timestamp rounded to hour matches prediction created_at rounded to hour
  ON DATE_TRUNC('hour', t.timestamp) >= DATE_TRUNC('hour', p.created_at - INTERVAL '24 hours')
  AND DATE_TRUNC('hour', t.timestamp) < DATE_TRUNC('hour', p.created_at + INTERVAL '1 hour')
WHERE t.timestamp IS NOT NULL 
  AND p.predicted_value IS NOT NULL;

-- Grant public access for Looker
GRANT SELECT ON actual_vs_predicted TO anon;
GRANT SELECT ON actual_vs_predicted TO authenticated;
"""

try:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
            conn.commit()
            print("✅ Created improved actual_vs_predicted view with hourly matching")
            
            # Test the view
            cur.execute("SELECT COUNT(*) as row_count FROM actual_vs_predicted;")
            count = cur.fetchone()[0]
            print(f"📊 View returned {count} matching records")
            
            if count > 0:
                cur.execute("""
                    SELECT 
                        actual_timestamp, 
                        fuel_type, 
                        actual_value, 
                        predicted_value,
                        error_percentage
                    FROM actual_vs_predicted 
                    LIMIT 5;
                """)
                print("\n📈 Sample matches:")
                for row in cur.fetchall():
                    print(f"  {row[0]} ({row[1]}): actual={row[2]}, predicted={row[3]}, error={row[4]}%")
            else:
                print("⚠️  No matches found yet. Data timestamps may be too recent.")
                
except Exception as e:
    print(f"❌ Error: {e}")
