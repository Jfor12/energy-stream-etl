#!/usr/bin/env python3
"""
Test actual vs predicted view by inserting matching historical data
"""

import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase import create_client, Client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("❌ Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in .env")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

print("=" * 60)
print("🔍 ACTUAL VS PREDICTED VIEW TEST")
print("=" * 60)

# Get recent predictions
print("\n📊 Fetching recent predictions...")
predictions_result = supabase.table('grid_predictions').select('*').order('created_at', desc=True).limit(10).execute()

if not predictions_result.data:
    print("❌ No predictions found. Run forecasting first.")
    sys.exit(1)

predictions = predictions_result.data
print(f"✅ Found {len(predictions)} recent predictions")

# Get unique prediction timestamps
pred_timestamps = set(p['prediction_timestamp'] for p in predictions)
print(f"📅 Unique prediction timestamps: {len(pred_timestamps)}")

# Insert test telemetry data matching prediction timestamps
print("\n📤 Inserting test telemetry data matching prediction timestamps...")

test_telemetry = []
for pred_ts_str in list(pred_timestamps)[:3]:  # Use first 3 unique timestamps
    pred_ts = datetime.fromisoformat(pred_ts_str)
    
    test_telemetry.append({
        'timestamp': pred_ts.isoformat(),
        'overall_intensity': 150,
        'fuel_gas_perc': 35.5,
        'fuel_nuclear_perc': 20.0,
        'fuel_wind_perc': 42.3,
        'fuel_solar_perc': 2.2
    })

result = supabase.table('grid_telemetry').insert(test_telemetry).execute()
print(f"✅ Inserted {len(test_telemetry)} telemetry records")

# Query the view
print("\n🔗 Querying actual_vs_predicted view...")
view_result = supabase.table('actual_vs_predicted').select('*').order('prediction_timestamp', desc=True).execute()

if not view_result.data:
    print("⚠️  View is still empty. Checking for data...")
    
    # Debug: check what's in the view
    print("\n🔍 Debugging: Checking individual queries...")
    
    # Check telemetry
    telem = supabase.table('grid_telemetry').select('timestamp, fuel_wind_perc').order('timestamp', desc=True).limit(5).execute()
    print(f"Recent telemetry records: {len(telem.data)}")
    if telem.data:
        for t in telem.data[:3]:
            print(f"  - {t['timestamp']}")
    
    # Check predictions
    preds = supabase.table('grid_predictions').select('prediction_timestamp, fuel_type').order('created_at', desc=True).limit(5).execute()
    print(f"Recent predictions: {len(preds.data)}")
    if preds.data:
        for p in preds.data[:3]:
            print(f"  - {p['prediction_timestamp']} ({p['fuel_type']})")
else:
    print(f"✅ View has {len(view_result.data)} matching records!")
    
    # Display sample comparison
    print("\n📊 Sample Actual vs Predicted Comparisons:")
    print("-" * 80)
    print(f"{'Metric':<15} {'Actual':<12} {'Predicted':<12} {'Error':<10} {'Error %':<10}")
    print("-" * 80)
    
    for record in view_result.data[:10]:
        fuel = record['fuel_type']
        actual = record['actual_value']
        predicted = record['predicted_value']
        error = record['prediction_error']
        error_pct = record['error_percentage']
        
        actual_str = f"{actual:.2f}" if actual else "N/A"
        predicted_str = f"{predicted:.2f}"
        error_str = f"{error:.2f}" if error else "N/A"
        error_pct_str = f"{error_pct:.2f}%" if error_pct else "N/A"
        
        print(f"{fuel:<15} {actual_str:<12} {predicted_str:<12} {error_str:<10} {error_pct_str:<10}")

print("\n" + "=" * 60)
print("✅ View test complete!")
print("=" * 60)
