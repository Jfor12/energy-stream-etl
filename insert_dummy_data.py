#!/usr/bin/env python3
"""
Insert 24 hours of dummy telemetry data for testing actual_vs_predicted view.
This triggers the webhook → Edge Function → predictions.
"""

import os
import psycopg
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv('DATABASE_URL')

if not DB_URL:
    print('❌ DATABASE_URL not set')
    exit(1)

# Realistic grid data patterns
def generate_hourly_data(hours=24):
    """Generate 24 hours of realistic grid telemetry data."""
    data = []
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    
    for i in range(hours):
        timestamp = now + timedelta(hours=i)
        hour_of_day = timestamp.hour
        
        # Simulate realistic patterns
        # Carbon intensity higher during day, lower at night
        if 6 <= hour_of_day <= 22:  # Daytime
            overall_intensity = 95 + (i % 20)  # 95-115 gCO2/kWh
            wind_pct = 40 + (i % 15)  # 40-55%
            solar_pct = 5 + (i % 8)    # 5-13% (peaks mid-day)
        else:  # Night
            overall_intensity = 80 + (i % 10)  # 80-90 gCO2/kWh
            wind_pct = 50 + (i % 20)  # 50-70% (more wind at night)
            solar_pct = 0.5            # Nearly zero
        
        gas_pct = 100 - wind_pct - solar_pct - 10  # Remaining
        nuclear_pct = 10                            # Steady
        
        data.append({
            'timestamp': timestamp,
            'overall_intensity': int(overall_intensity),
            'fuel_wind_perc': round(wind_pct, 1),
            'fuel_solar_perc': round(solar_pct, 1),
            'fuel_gas_perc': round(gas_pct, 1),
            'fuel_nuclear_perc': nuclear_pct,
        })
    
    return data

def insert_dummy_data():
    """Insert dummy data into grid_telemetry table."""
    data = generate_hourly_data(24)
    
    try:
        with psycopg.connect(DB_URL, sslmode='require') as conn:
            with conn.cursor() as cur:
                print('📊 Inserting 24 hours of dummy telemetry data...\n')
                
                for record in data:
                    cur.execute('''
                        INSERT INTO grid_telemetry 
                        (timestamp, overall_intensity, fuel_wind_perc, fuel_solar_perc, fuel_gas_perc, fuel_nuclear_perc)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (
                        record['timestamp'],
                        record['overall_intensity'],
                        record['fuel_wind_perc'],
                        record['fuel_solar_perc'],
                        record['fuel_gas_perc'],
                        record['fuel_nuclear_perc'],
                    ))
                    
                    print(f"✅ {record['timestamp']}: {record['overall_intensity']} gCO2/kWh | "
                          f"Wind: {record['fuel_wind_perc']}% | Solar: {record['fuel_solar_perc']}%")
                
                conn.commit()
                print(f'\n🎉 Inserted {len(data)} rows successfully!')
                print('⏳ Waiting 10 seconds for Edge Function to generate predictions...')
                print('📈 Then query: SELECT * FROM actual_vs_predicted LIMIT 20;')
                
    except Exception as e:
        print(f'❌ Error: {e}')
        exit(1)

if __name__ == '__main__':
    insert_dummy_data()
