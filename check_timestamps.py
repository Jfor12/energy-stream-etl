#!/usr/bin/env python3
"""Check timestamp alignment between grid_telemetry and grid_predictions."""

import os
import psycopg
from datetime import datetime

DB_URL = 'postgresql://postgres.unrhldictkhzmbtyiuti:romano10romano20@aws-1-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require'

try:
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            # Check grid_telemetry columns
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name='grid_telemetry'
                ORDER BY ordinal_position;
            """)
            print("📋 grid_telemetry columns:")
            for row in cur.fetchall():
                print(f"  {row[0]}: {row[1]}")
            
            print("\n")
            
            # Check grid_predictions columns
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name='grid_predictions'
                ORDER BY ordinal_position;
            """)
            print("📋 grid_predictions columns:")
            for row in cur.fetchall():
                print(f"  {row[0]}: {row[1]}")
            
            print("\n")
            
            # Sample data from both tables
            cur.execute("""
                SELECT timestamp, overall_intensity 
                FROM grid_telemetry 
                ORDER BY timestamp DESC 
                LIMIT 3;
            """)
            print("📊 Recent grid_telemetry samples:")
            for row in cur.fetchall():
                print(f"  {row[0]}: {row[1]} gCO2/kWh")
            
            print("\n")
            
            cur.execute("""
                SELECT prediction_timestamp, predicted_value, fuel_type
                FROM grid_predictions 
                ORDER BY prediction_timestamp DESC 
                LIMIT 3;
            """)
            print("📊 Recent grid_predictions samples:")
            for row in cur.fetchall():
                print(f"  {row[0]} ({row[2]}): {row[1]}")
                
except Exception as e:
    print(f"❌ Error: {e}")
