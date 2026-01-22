# Supabase Integration Guide

## Overview
Your energy-stream-etl project is now linked to Supabase project `unrhldictkhzmbtyiuti`. This enables:
- Real-time database webhooks
- Edge Functions for predictive analytics
- Automated forecasting loop

## Setup Completed ✅

### 1. **Environment Configuration**
Your `.env` file contains:
- `SUPABASE_URL`: Your project endpoint
- `SUPABASE_ANON_KEY`: Public API key
- `SUPABASE_SERVICE_ROLE_KEY`: Admin API key

**Security Note**: Never commit `.env` to GitHub. It's in `.gitignore`.

### 2. **Database Schema**
The migration file `supabase/migrations/001_create_predictions_table.sql` creates:
- `grid_predictions` table: Stores forecasted values
- `actual_vs_predicted` view: Compares actuals vs predictions

**To apply the migration**:
```bash
# Run directly in Supabase SQL Editor, or via Supabase CLI once installed
supabase db push
```

### 3. **Edge Function: grid-forecaster**
Located at `supabase/functions/grid-forecaster/index.ts`

**What it does**:
1. Fetches the last 24 hours of wind generation data
2. Sends to Hugging Face's Chronos model for 6-hour forecast
3. Stores predictions in `grid_predictions` table

## Next Steps

### Step 1: Configure Hugging Face Token
1. Go to https://huggingface.co/settings/tokens
2. Create a new token (scope: "read")
3. Update `.env`:
```bash
HF_TOKEN=hf_your_token_here
```

### Step 2: Apply Database Schema
1. Go to Supabase Dashboard → SQL Editor
2. Paste contents of `supabase/migrations/001_create_predictions_table.sql`
3. Run the query

### Step 3: Deploy Edge Function
Once Supabase CLI is available, deploy with:
```bash
supabase functions deploy grid-forecaster
```

### Step 4: Create Database Webhook
In Supabase Dashboard → Database → Webhooks:
- **Name**: run_forecast_on_insert
- **Table**: grid_telemetry
- **Event**: INSERT
- **Type**: Edge Function
- **Function**: grid-forecaster

This automatically triggers forecasting whenever ETL inserts new data.

## Testing the Integration

### Test the Edge Function Locally
```bash
supabase functions serve
```

### Test from Python (etl_job.py)
```python
import os
from supabase import create_client, Client

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
supabase: Client = create_client(url, key)

# Insert test telemetry data
supabase.table('grid_telemetry').insert({
    'timestamp': 'now',
    'fuel_wind_perc': 45.5
}).execute()

# This will automatically trigger grid-forecaster via webhook
```

## Troubleshooting

### Edge Function not triggering?
- Check webhook is enabled in Supabase Dashboard
- Verify `grid-forecaster` function is deployed
- Check function logs in Supabase Dashboard

### Predictions not appearing?
- Verify Hugging Face token is valid
- Check function execution logs for HF API errors
- Ensure `grid_predictions` table exists

### Performance
- Function timeout: 120 seconds (default)
- Predictions stored within seconds of ETL insert
- No additional infrastructure costs (free tier)

## Architecture Diagram

```
GitHub Action (hourly)
         ↓
    etl_job.py (fetch + transform)
         ↓
  INSERT into grid_telemetry
         ↓
   [Database Webhook]
         ↓
  grid-forecaster Edge Function
         ↓
  Call Hugging Face API
         ↓
  INSERT into grid_predictions
         ↓
  [View/Dashboard] actual_vs_predicted
```

## Documentation
- Supabase Docs: https://supabase.com/docs
- Edge Functions: https://supabase.com/docs/guides/functions
- Hugging Face: https://huggingface.co/docs/api-inference
