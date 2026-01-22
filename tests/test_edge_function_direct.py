#!/usr/bin/env python3
"""
Direct test of the grid-forecaster Edge Function
"""

import os
import requests
import json
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("❌ Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in .env")
    exit(1)

# The Edge Function URL
FUNCTION_URL = f"{SUPABASE_URL}/functions/v1/grid-forecaster"

headers = {
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

print("=" * 60)
print("🧪 DIRECT EDGE FUNCTION TEST")
print("=" * 60)
print(f"\n📍 Calling: {FUNCTION_URL}")
print(f"🔑 Auth header: Bearer {SUPABASE_SERVICE_ROLE_KEY[:30]}...")

try:
    response = requests.post(FUNCTION_URL, headers=headers, json={}, timeout=15)
    print(f"\n✅ Response Status: {response.status_code}")
    print(f"📄 Response Body:")
    print(json.dumps(response.json(), indent=2))
except requests.exceptions.Timeout:
    print(f"⏱️  Request timed out (>15s) - function may be processing")
except requests.exceptions.ConnectionError as e:
    print(f"❌ Connection error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
