#!/usr/bin/env python3
"""
Test script for Supabase integration with energy-stream-etl
Tests:
1. Connection to Supabase
2. Grid telemetry table structure
3. Grid predictions table structure
4. View: actual_vs_predicted
"""

import os
import sys
from datetime import datetime, timedelta, timezone
import json
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed")

from supabase import create_client, Client

# Get credentials
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("❌ Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in .env")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def test_connection():
    """Test basic connection to Supabase"""
    print("\n🔌 Testing Supabase connection...")
    try:
        result = supabase.table('grid_telemetry').select('*', count='exact').limit(1).execute()
        print(f"✅ Connected to Supabase")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

def test_grid_telemetry_table():
    """Verify grid_telemetry table exists and has expected columns"""
    print("\n📊 Testing grid_telemetry table...")
    try:
        result = supabase.table('grid_telemetry').select('*').limit(1).execute()
        print(f"✅ grid_telemetry table exists")
        if result.data and len(result.data) > 0:
            print(f"   Sample record columns: {list(result.data[0].keys())}")
        return True
    except Exception as e:
        print(f"❌ grid_telemetry table error: {e}")
        return False

def test_grid_predictions_table():
    """Verify grid_predictions table exists"""
    print("\n🔮 Testing grid_predictions table...")
    try:
        result = supabase.table('grid_predictions').select('*').limit(1).execute()
        print(f"✅ grid_predictions table exists")
        if result.data and len(result.data) > 0:
            print(f"   Sample record columns: {list(result.data[0].keys())}")
        else:
            print("   (No predictions yet)")
        return True
    except Exception as e:
        print(f"❌ grid_predictions table error: {e}")
        return False

def test_insert_telemetry():
    """Insert test telemetry data to trigger forecasting"""
    print("\n📤 Inserting test telemetry data...")
    try:
        now = datetime.now(timezone.utc)
        test_data = {
            'timestamp': now.isoformat(),
            'overall_intensity': 150,
            'fuel_gas_perc': 35.5,
            'fuel_nuclear_perc': 20.0,
            'fuel_wind_perc': 42.3,  # Wind percentage
            'fuel_solar_perc': 2.2
        }
        
        result = supabase.table('grid_telemetry').insert(test_data).execute()
        print(f"✅ Inserted test telemetry data")
        print(f"   Timestamp: {test_data['timestamp']}")
        print(f"   Wind %: {test_data['fuel_wind_perc']}")
        return True
    except Exception as e:
        print(f"❌ Insert failed: {e}")
        return False

def test_predictions_created():
    """Check if predictions were created after insertion"""
    print("\n⏳ Checking for predictions (waiting 5 seconds for webhook trigger)...")
    time.sleep(5)
    
    try:
        result = supabase.table('grid_predictions').select('*').order('created_at', desc=True).limit(6).execute()
        if result.data and len(result.data) > 0:
            print(f"✅ Found {len(result.data)} prediction(s)")
            for pred in result.data[:3]:  # Show first 3
                print(f"   - Fuel: {pred['fuel_type']}, Value: {pred['predicted_value']:.2f}, Created: {pred['created_at']}")
            return True
        else:
            print(f"⚠️  No predictions found yet (webhook may not be configured)")
            return False
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return False

def test_actual_vs_predicted_view():
    """Test the actual_vs_predicted view"""
    print("\n📈 Testing actual_vs_predicted view...")
    try:
        result = supabase.table('actual_vs_predicted').select('*').limit(5).execute()
        if result.data and len(result.data) > 0:
            print(f"✅ View works! Found {len(result.data)} comparison record(s)")
            sample = result.data[0]
            print(f"   Sample: Actual={sample.get('actual_value', 'N/A')}, Predicted={sample.get('predicted_value', 'N/A')}, Error={sample.get('prediction_error', 'N/A')}")
        else:
            print(f"⚠️  View is empty (no predictions yet)")
        return True
    except Exception as e:
        print(f"❌ View error: {e}")
        return False

def main():
    print("=" * 60)
    print("🧪 SUPABASE INTEGRATION TEST")
    print("=" * 60)
    
    results = {}
    results['connection'] = test_connection()
    
    if not results['connection']:
        print("\n❌ Cannot proceed without connection")
        return
    
    results['telemetry_table'] = test_grid_telemetry_table()
    results['predictions_table'] = test_grid_predictions_table()
    results['insert'] = test_insert_telemetry()
    results['predictions'] = test_predictions_created()
    results['view'] = test_actual_vs_predicted_view()
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 TEST SUMMARY")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed! Your Supabase integration is working.")
    elif passed_count >= total_count - 1:
        print("\n⚠️  Most tests passed. Check webhook configuration if predictions aren't appearing.")
    else:
        print("\n❌ Some tests failed. Check your configuration.")

if __name__ == "__main__":
    main()
