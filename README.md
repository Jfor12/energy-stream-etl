# ⚡ National Grid Telemetry Pipeline

An automated data engineering pipeline that monitors National Grid carbon intensity in real-time. It ingests live generation mix (Solar, Wind, Gas, Nuclear) and archives telemetry for historical analysis.

**Architecture:**
- **Ingestion (GitHub Actions)**: Hourly cron hits the National Grid ESO API (free)
- **Storage (PostgreSQL/Supabase)**: Validated telemetry stored as time-series
- **Analytics (SQL/Looker)**: Dashboard and views for renewable trends

---

## 🌟 Features
- ✅ **Automated ETL**: Hourly GitHub Actions job - completely free
- ✅ **Production logging**: Structured logging with timestamps
- ✅ **Retry logic**: Exponential backoff for API failures (3 retries)
- ✅ **Data quality checks**: Null validation, type checking, value ranges
- ✅ **Duplicate prevention**: Automatic timestamp-based deduplication
- ✅ **ETL metadata tracking**: Run history with success/failure status
- ✅ **Unit tested**: 12 pytest tests covering core functions
- ✅ **Postgres-first**: Schema ready for Supabase or any managed Postgres
- ✅ **Predictive analytics**: 24-hour forecasting with ensemble methods
- ✅ **Accuracy tracking**: Real vs. forecasted comparisons

---

## 🛠️ Tech Stack
- **Python 3.9+** - Core runtime
- **PostgreSQL** via `psycopg` v3 - Time-series database
- **Requests** - National Grid ESO Carbon Intensity API
- **GitHub Actions** - Free hourly scheduling
- **pytest** - Unit testing
- **Supabase** - Database and Edge Functions
- **Hugging Face** - AI forecasting models

---

## 🚀 Quick Start

### 1. Local Development
```bash
git clone https://github.com/Jfor12/flight-data-pipeline.git
cd flight-data-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env file
echo "DATABASE_URL=postgresql://user:password@host:port/dbname" > .env

# Run ETL once
python etl_job.py
```

### 2. Deploy to GitHub Actions (Free!)

**Push code:**
```bash
git add .
git commit -m "Add Grid ETL pipeline"
git push origin main
```

**Add DATABASE_URL secret:**
1. GitHub repo → Settings → Secrets and variables → Actions
2. Click: New repository secret
3. Name: `DATABASE_URL`
4. Value: `postgresql://user:password@host:port/dbname`
5. Save

**That's it!** ✅ Your pipeline runs hourly starting next :00 UTC

---

## 📊 How It Works

### ETL Pipeline (`etl_job.py`)

**Every hour:**
- Calls `https://api.carbonintensity.org.uk/intensity` for carbon intensity
- Calls `https://api.carbonintensity.org.uk/generation` for fuel mix
- Validates data (null checks, type checking, range validation)
- **Checks for duplicates** - skips if timestamp already exists
- Stores to PostgreSQL `grid_telemetry` table
- Logs execution to `etl_runs` table

**Production features:**
- Structured logging to file + console
- Exponential backoff retry (3 attempts, 2-8s delays)
- Data quality validation (0-1000 gCO2/kWh, 0-100% fuel percentages)
- **Duplicate prevention** - timestamp-based deduplication before insert
- Automatic table creation
- Transactional database writes with rollback

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS grid_telemetry (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    overall_intensity INT,
    fuel_gas_perc DOUBLE PRECISION,
    fuel_nuclear_perc DOUBLE PRECISION,
    fuel_wind_perc DOUBLE PRECISION,
    fuel_solar_perc DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS etl_runs (
    id BIGSERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20),
    rows_inserted INT,
    execution_time_ms INT,
    error_message TEXT
);
```

---

## 🔮 Supabase Predictive Analytics (Version 2)

Your pipeline now includes **automated forecasting** via Supabase Edge Functions and Hugging Face AI!

### What's New

**Forecasting Loop:**
- Database webhook triggers on every new ETL insert
- Edge Function pulls last 24 hours of wind data
- Generates 6-hour wind generation predictions
- Stores forecasts in `grid_predictions` table
- Compare actual vs predicted in `actual_vs_predicted` view

### Setup Instructions

#### Step 1: Create Supabase Project
1. Go to [supabase.com](https://supabase.com) and sign up (free)
2. Create a new project
3. Save your **Project Ref** and **Project URL**

#### Step 2: Get API Keys
1. Supabase Dashboard → **Settings** → **API**
2. Copy:
   - `SUPABASE_URL` (Project URL)
   - `SUPABASE_ANON_KEY` (Anon key)
   - `SUPABASE_SERVICE_ROLE_KEY` (Service role key)

#### Step 3: Configure Environment
Add to your `.env` file:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
HF_TOKEN=your_hugging_face_token
```

#### Step 4: Create Database Schema
1. Go to Supabase Dashboard → **SQL Editor**
2. Create new query
3. Paste contents of `supabase/migrations/001_create_predictions_table.sql`
4. Run query

This creates:
- `grid_predictions` table for forecasts
- `actual_vs_predicted` view for comparison

#### Step 5: Get Hugging Face Token
1. Go to [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Create new token (scope: "read")
3. Add to `.env` as `HF_TOKEN`

#### Step 6: Deploy Edge Function
1. Go to Supabase Dashboard → **Edge Functions**
2. Click **Create a new function**
3. Name: `grid-forecaster`
4. Copy code from `supabase/functions/grid-forecaster/index.ts`
5. Paste and **Deploy**

#### Step 7: Add Secret to Edge Function
1. Go to **Edge Functions** → **grid-forecaster** → **Settings**
2. Add secret:
   - Key: `HF_TOKEN`
   - Value: `hf_your_token_here`

#### Step 8: Create Database Webhook
1. Go to Supabase Dashboard → **Database** → **Webhooks**
2. Click **Create a new webhook**
3. Configure:
   - **Name:** `run_forecast_on_insert`
   - **Table:** `grid_telemetry`
   - **Events:** `Insert`
   - **Type:** `Supabase Edge Functions`
   - **Function:** `grid-forecaster`
4. Click **Save**

#### Step 9: Test the Integration
```bash
python test_supabase_integration.py
```

Expected output:
```
✅ PASS: connection
✅ PASS: telemetry_table
✅ PASS: predictions_table
✅ PASS: insert
✅ PASS: predictions
✅ PASS: view

🎉 All tests passed! Your Supabase integration is working.
```

### How It Works

```
Every hour:
  etl_job.py fetches grid data
  ↓
  INSERT into grid_telemetry
  ↓
  Webhook detects INSERT
  ↓
  grid-forecaster Edge Function runs
  ↓
  Fetches last 72 hours of historical data
  ↓
  Data smoothing (removes outliers)
  ↓
  Ensemble forecasting: 70% Hugging Face AI + 30% Statistical
  ↓
  Generates 24-hour forecast for all 5 metrics
  ↓
  INSERT into grid_predictions (120 predictions)
  ↓
  actual_vs_predicted view updated
  ↓
  Data ready for analytics/Looker
```

### Forecasting Enhancements (v2)

The improved forecasting system includes:

**1. Extended Historical Context**
- Uses 72 hours (3 days) of data instead of 24 hours
- Captures weekly and daily patterns
- Better seasonal awareness

**2. Data Pre-processing**
- Moving average smoothing (window of 3)
- Removes outliers and noise
- Improves model accuracy

**3. Advanced Statistical Forecast**
- Calculates trend, volatility, and seasonality
- Uses sine wave for cyclical patterns
- Adaptive noise based on historical variance

**4. Ensemble Prediction Method**
- Blends two approaches:
  - **70%** Hugging Face Chronos AI model
  - **30%** Statistical forecast
- Robust fallback if AI API unavailable
- Better generalisation across metrics

**5. All 5 Metrics Forecasted**
- Overall_Intensity (carbon intensity)
- Wind generation %
- Solar generation %
- Gas generation %
- Nuclear generation %

**6. Accuracy Tracking**
- `actual_vs_predicted` view compares forecasts to actual data
- Calculates absolute and percentage errors
- Tracks forecast quality over time

### Querying Predictions and Accuracy

**View latest predictions:**
```sql
SELECT * FROM grid_predictions 
ORDER BY created_at DESC 
LIMIT 10;
```

**Compare actual vs predicted:**
```sql
SELECT 
  actual_timestamp,
  prediction_timestamp,
  fuel_type,
  actual_value,
  predicted_value,
  prediction_error,
  error_percentage
FROM actual_vs_predicted 
ORDER BY prediction_timestamp DESC 
LIMIT 20;
```

**Forecast accuracy by metric (best-performing metrics first):**
```sql
SELECT 
  fuel_type,
  COUNT(*) as total_forecasts,
  ROUND(AVG(ABS(prediction_error)), 2) AS avg_absolute_error,
  ROUND(AVG(error_percentage), 2) AS avg_error_pct,
  ROUND(STDDEV(error_percentage), 2) AS error_std_dev,
  MIN(error_percentage) AS best_pct,
  MAX(error_percentage) AS worst_pct
FROM actual_vs_predicted
WHERE actual_value IS NOT NULL
GROUP BY fuel_type
ORDER BY avg_error_pct ASC;
```

**Forecast performance over time (track improvement):**
```sql
SELECT 
  DATE(prediction_timestamp) as forecast_date,
  fuel_type,
  COUNT(*) as predictions,
  ROUND(AVG(error_percentage), 2) as daily_avg_error_pct,
  ROUND(MAX(error_percentage), 2) as daily_worst_error_pct
FROM actual_vs_predicted
WHERE actual_value IS NOT NULL
GROUP BY DATE(prediction_timestamp), fuel_type
ORDER BY forecast_date DESC, fuel_type;
```

**Find poor predictions (>50% error) for investigation:**
```sql
SELECT 
  actual_timestamp,
  prediction_timestamp,
  fuel_type,
  actual_value,
  predicted_value,
  error_percentage
FROM actual_vs_predicted
WHERE error_percentage > 50 
  AND actual_value IS NOT NULL
ORDER BY error_percentage DESC, prediction_timestamp DESC;
```

**Weekly accuracy trends:**
```sql
SELECT 
  DATE_TRUNC('week', prediction_timestamp) as week_start,
  fuel_type,
  COUNT(*) as total_predictions,
  ROUND(AVG(error_percentage), 2) as weekly_avg_error_pct,
  ROUND(STDDEV(error_percentage), 2) as weekly_std_dev
FROM actual_vs_predicted
WHERE actual_value IS NOT NULL
GROUP BY DATE_TRUNC('week', prediction_timestamp), fuel_type
ORDER BY week_start DESC, fuel_type;
```

### Files Added

- `supabase/config.json` — Project configuration
- `supabase/migrations/001_create_predictions_table.sql` — Database schema
- `supabase/functions/grid-forecaster/index.ts` — Edge Function code
- `test_supabase_integration.py` — Integration test
- `test_edge_function_direct.py` — Function test
- `docs/SUPABASE_SETUP.md` — Detailed setup guide

### Troubleshooting

**Predictions not appearing?**
- Check webhook is enabled in Supabase Dashboard
- Verify Edge Function is deployed and active
- Check function logs: Dashboard → Edge Functions → grid-forecaster → Logs
- Ensure telemetry data is being inserted correctly

**HF_TOKEN errors?**
- Ensure token is added to Edge Function secrets
- Verify token has "read" scope from Hugging Face
- Regenerate token if experiencing 401 errors

**Slow predictions?**
- First request after deployment loads AI model (~30-60s)
- Subsequent requests are fast (<5s)
- Statistical fallback is used if model unavailable

**Poor forecast accuracy?**
- Ensure at least 72 hours of historical data exists
- Check data quality in `grid_telemetry` table
- Review error percentages in `actual_vs_predicted` view
- Adjust ensemble blend ratio (currently 70% HF / 30% statistical)

### Cost

| Component | Cost |
|-----------|------|
| Supabase (free tier) | £0 |
| Edge Functions (free: 2M req/month) | £0 |
| Hugging Face (free tier) | £0 |
| **TOTAL** | **£0** |

All completely free! ✅

---

## 🧪 Testing

Run unit tests locally:
```bash
PYTHONPATH=. pytest tests/test_etl.py -v
```

**Test Coverage:**
- ✅ Data validation (null, type, range checks)
- ✅ ISO8601 timestamp parsing
- ✅ Integration test for full validation pipeline
- ✅ Error handling for invalid data
- ✅ Duplicate prevention logic

**Example output:**
```
tests/test_etl.py::TestDataValidation::test_validate_intensity_valid PASSED
tests/test_etl.py::TestDataValidation::test_validate_intensity_invalid PASSED
tests/test_etl.py::TestDataValidation::test_validate_fuel_percentage_valid PASSED
tests/test_etl.py::TestDateParsing::test_parse_iso8601_valid PASSED
tests/test_etl.py::TestIntegration::test_full_validation_pipeline PASSED
tests/test_etl.py::TestDuplicatePrevention::test_duplicate_detection_logic PASSED

============================== 12 passed in 1.27s ===============================
```

Run with coverage:
```bash
pytest tests/ --cov=etl_job --cov-report=html
```

---

## 🔁 GitHub Actions Workflow

Workflow file: `.github/workflows/etl.yml`

**What it does:**
- Runs hourly at :00 UTC (configurable with cron)
- Clones your code
- Installs dependencies (cached)
- Runs `python etl_job.py`
- Injects `DATABASE_URL` from secrets
- Uploads logs on failure (30-day retention)

**Monitor runs:**
- Repository → Actions tab
- See all runs with timestamps and status
- Click any run to view full logs
- Manual trigger available: "Run workflow" button

---

## 📈 Monitoring Your Pipeline

### Query Success Rate
```sql
SELECT 
  DATE(run_timestamp) AS day,
  COUNT(*) AS total_runs,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful,
  ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) AS success_pct
FROM etl_runs
WHERE run_timestamp >= NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1 DESC;
```

### View Recent Runs
```sql
SELECT run_timestamp, status, rows_inserted, execution_time_ms, error_message
FROM etl_runs
ORDER BY run_timestamp DESC
LIMIT 10;
```

### Check Data
```sql
SELECT COUNT(*) FROM grid_telemetry;
SELECT * FROM grid_telemetry ORDER BY timestamp DESC LIMIT 5;
```

---

## 🔑 Environment Variables
- `DATABASE_URL` — Required. Postgres connection string: `postgresql://user:password@host:port/dbname`
  - **Local**: Set in `.env` file
  - **GitHub Actions**: Set as repository secret

---

## 🧰 Troubleshooting

**Workflow not running:**
- Wait until next hour (:00 UTC)
- Or manually trigger: Actions tab → Run workflow
- Check workflow file exists: `.github/workflows/etl.yml` ✓

**Failed run:**
- Click failed run in Actions tab
- View logs to see error details
- Common issue: `DATABASE_URL` secret not set

**No data in database:**
- Verify `DATABASE_URL` is correct: `psql "$DATABASE_URL"`
- Test locally: `python etl_job.py`
- Check `etl_runs` table for error messages

**API failures:**
- Logs show retry attempts (exponential backoff)
- Usually transient - will succeed on next hourly run
- Check `etl_pipeline.log` for details

---

## 💰 Cost

| Component | Cost | Notes |
|-----------|------|-------|
| GitHub Actions | £0 | 2,000 free min/month |
| Supabase DB | £0 | Free tier 500MB |
| Pipeline usage | £0 | ~360 min/month (18%) |
| **TOTAL** | **£0** | **Forever free** ✅ |

---

## 🎯 Use Cases

**Monitor grid cleanliness:**
- Identify hours with high renewable generation
- Plan energy-intensive tasks during green windows

**Analyse trends:**
- Track wind and solar percentage over time
- Compare regions and seasons

**Optimise consumption:**
- EV charging during low-carbon hours
- Cloud compute job scheduling

---

## 📁 Project Structure

```
energy-stream-etl/
├── etl_job.py                  # Production ETL with logging + validation
├── requirements.txt            # Python dependencies
├── tests/
│   └── test_etl.py             # 12 unit tests
├── .github/
│   └── workflows/
│       └── etl.yml             # GitHub Actions schedule
├── docs/
│   └── GITHUB_ACTIONS_SETUP.md # Detailed setup guide
├── README.md                   # This file
└── supabase/
    ├── config.json             # Project configuration
    ├── migrations/
    │   └── 001_create_predictions_table.sql
    └── functions/
        └── grid-forecaster/
            └── index.ts        # Edge Function code
```

---

## 🚀 Next Steps

1. ✅ Deploy to GitHub (push code + add secret)
2. ✅ Wait for first run (next :00 UTC)
3. ✅ Check Actions tab for logs
4. ✅ Query database to verify data
5. ✅ Set up Looker dashboard
6. ✅ Monitor with SQL queries

---

## 👤 Built by
**Jfor12** — [🐙 GitHub](https://github.com/Jfor12) | [💼 LinkedIn](https://linkedin.com/in/jacopofornesi)

---

## 🚀 Quick Start (Local)

1) Clone and install dependencies
```bash
cd energy-stream-etl
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Set environment
Create a `.env` file:
```env
DATABASE_URL=postgresql://user:password@host:port/dbname
```

3) Create the tables
```sql
CREATE TABLE IF NOT EXISTS grid_telemetry (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    overall_intensity INT,
    fuel_gas_perc DOUBLE PRECISION,
    fuel_nuclear_perc DOUBLE PRECISION,
    fuel_wind_perc DOUBLE PRECISION,
    fuel_solar_perc DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS etl_runs (
    id BIGSERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ DEFAULT NOW(),
    status VARCHAR(20),
    rows_inserted INT,
    execution_time_ms INT,
    error_message TEXT
);
```

4) Run the ETL once
```bash
python etl_job.py
```

Check logs in `etl_pipeline.log` for execution details.

5) (Optional) Run with Prefect
```bash
python prefect_flow.py
```

---

## ▶️ How It Works

### ETL Pipeline (`etl_job.py`)

**Data Ingestion**
- Calls `https://api.carbonintensity.org.uk/intensity` for current carbon intensity.
- Calls `https://api.carbonintensity.org.uk/generation` for fuel mix (wind, solar, gas, nuclear).
- **Retry logic**: 3 attempts with exponential backoff (2s, 4s, 8s delays).

**Data Quality Validation**
- **Null checks**: Ensures critical fields (timestamp, intensity) are not null.
- **Type validation**: Verifies data types match schema expectations.
- **Value ranges**: Carbon intensity (0-1000 gCO2/kWh), fuel percentages (0-100%).
- **Freshness check**: Flags data older than 2 hours.

**Logging & Monitoring**
- Structured logging to `etl_pipeline.log` and console.
- ETL metadata tracked in `etl_runs` table (status, execution time, errors).
- Log levels: INFO (normal flow), WARNING (retries), ERROR (failures).

**Database Operations**
- Auto-creates tables if missing (`grid_telemetry`, `etl_runs`).
- Transactional inserts with rollback on failure.
- Logs every run outcome for debugging and monitoring.

### Workflow Orchestration (`prefect_flow.py`)

Prefect provides:
- **Visual pipeline monitoring** - See task execution in Prefect UI.
- **Automatic retries** - Task-level retry configuration.
- **Parallel execution** - Fetch intensity and generation concurrently.
- **Schedule management** - Define cron schedules in code.

Run locally:
```bash
# Start Prefect server (optional, for UI)
prefect server start

# In another terminal, run the flow
python prefect_flow.py
```

Deploy to Prefect Cloud:
```bash
prefect deploy prefect_flow.py:grid_etl_flow -n "hourly-carbon-etl" -p default
```

### Analytics (SQL views)
Add a daily cleanliness view for trend analysis:
```sql
CREATE OR REPLACE VIEW view_daily_cleanliness AS
SELECT
  DATE(timestamp) AS day,
  AVG(overall_intensity) AS avg_intensity,
  AVG(fuel_wind_perc + fuel_solar_perc) AS avg_renewables_perc,
  AVG(fuel_gas_perc) AS avg_fossil_perc,
  COUNT(*) AS samples
FROM grid_telemetry
GROUP BY 1
ORDER BY 1 DESC;
```

### Looker Integration
Connect Looker to your PostgreSQL database and create explores/dashboards using:
- `grid_telemetry` table for time-series analysis
- `view_daily_cleanliness` for aggregated daily metrics
- `etl_runs` table for pipeline health monitoring
- Custom dimensions for green window detection and renewable percentage calculations

**Example Dashboard Metrics:**
- Carbon intensity trends (hourly, daily, weekly)
- Renewable vs. fossil fuel mix over time
- ETL pipeline reliability (success rate, avg execution time)
- Green window frequency analysis

---

## 🔁 GitHub Actions (Free, Scheduled ETL) ⭐

**Recommended for free hosting.** GitHub Actions runs your ETL job every hour automatically at no cost.

### Quick Setup

1) **Push code to GitHub**
   ```bash
   git add .
   git commit -m "Add Grid ETL pipeline"
   git push origin main
   ```

2) **Set DATABASE_URL secret**
   - Go to: GitHub repo → Settings → Secrets and variables → Actions
   - Click: New repository secret
   - Name: `DATABASE_URL`
   - Value: `postgresql://user:pass@host:port/dbname`
   - Click: Add secret

3) **Done!** 🎉
   - Workflow file is ready: `.github/workflows/etl.yml`
   - Runs every hour automatically (UTC)
   - View runs: Actions tab → Grid ETL

### What Happens

```
Every hour at :00 UTC:
  ✓ GitHub Actions spins up Ubuntu runner
  ✓ Clones your code
  ✓ Installs dependencies
  ✓ Runs: python etl_job.py
  ✓ DATABASE_URL injected from secrets
  ✓ Logs saved to artifacts (on failure)
  ✓ Job completes in ~30-60 seconds
```

### Monitor Runs

**GitHub Actions dashboard:**
1. Repository → Actions tab
2. See: All ETL runs with timestamps
3. Click run to see full logs
4. Check if completed ✅ or failed ❌

**Example run log:**
```
2025-12-09 15:00:00 - === Starting Grid ETL Pipeline ===
2025-12-09 15:00:01 - Fetching carbon intensity from https://api.carbonintensity.org.uk/intensity
2025-12-09 15:00:02 - Fetched intensity: 90 gCO2/kWh at 2025-12-09 14:30:00+00:00
2025-12-09 15:00:02 - Fetching generation mix from https://api.carbonintensity.org.uk/generation
2025-12-09 15:00:03 - Fetched generation mix: Wind=57.0%, Solar=1.1%
2025-12-09 15:00:03 - ✅ All data quality checks passed
2025-12-09 15:00:04 - ✅ Stored intensity=90, wind=57.0%
2025-12-09 15:00:04 - ETL run logged: success, 1 rows, 1180ms
```

### Troubleshooting

**Runs not appearing:**
- Wait until top of next hour (:00 UTC)
- Or manually trigger: Actions tab → Grid ETL → Run workflow

**Workflow shows ❌ failed:**
- Click run to see logs
- Common issue: `DATABASE_URL` secret not set
- Check: Settings → Secrets → DATABASE_URL exists

**API errors in logs:**
- Check: `etl_pipeline.log` artifact (attached to failed runs)
- Retry logic will handle temporary failures
- Look for "Retry in Xs" messages

### Free Tier Limits

- **Minutes per month**: 2,000 (plenty for hourly!)
- **Data storage**: 500MB for logs/artifacts
- **Concurrent jobs**: 20

**Your usage**: ~730 runs/month × ~30 seconds = ~360 minutes (~18% of limit) ✅

### Cost: $0 (Forever) ✅

---

## 🔑 Environment Variables
- `DATABASE_URL` — Required. Postgres connection string (format: `postgresql://user:pass@host:port/dbname`).
  - **Local**: Set in `.env` file
  - **GitHub Actions**: Set as repository secret (Settings → Secrets → DATABASE_URL)

---

## 🧰 Troubleshooting

**No data in database**
- Run `python etl_job.py` once to seed initial telemetry.
- Check `etl_pipeline.log` for execution details and errors.
- Query `etl_runs` table to see pipeline execution history.

**API failures**
- Check logs for retry attempts and backoff timing.
- Verify network connectivity to `api.carbonintensity.org.uk`.
- API updates every 30 minutes; occasional 404s are normal for future timestamps.

**Data quality validation failures**
- Check logs for specific validation errors (null, type, range).
- Inspect `etl_runs.error_message` column for detailed error context.
- Carbon intensity should be 0-1000 gCO2/kWh, fuel percentages 0-100%.

**Connection errors**
- Confirm `DATABASE_URL` is set correctly in `.env` or environment.
- Ensure SSL is enabled (`sslmode=require` for Supabase).
- Test connection: `psql "$DATABASE_URL"`

**GitHub Actions failures**
- Verify `DATABASE_URL` secret is set in repository settings.
- Check workflow logs in Actions tab.
- Ensure hourly cron doesn't conflict with API rate limits (none documented).

---

## 📊 Monitoring ETL Health

Query ETL run history:
```sql
-- Recent ETL runs
SELECT run_timestamp, status, rows_inserted, execution_time_ms, error_message
FROM etl_runs
ORDER BY run_timestamp DESC
LIMIT 20;

-- Success rate (last 7 days)
SELECT 
  DATE(run_timestamp) AS day,
  COUNT(*) AS total_runs,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful_runs,
  ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) AS success_rate_pct,
  AVG(execution_time_ms) AS avg_execution_ms
FROM etl_runs
WHERE run_timestamp >= NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1 DESC;
```

---

## 📁 Project Structure

```
flight-data-pipeline/
├── etl_job.py              # Main ETL script with logging, validation, retry
├── prefect_flow.py         # Prefect workflow orchestration
├── requirements.txt        # Python dependencies
├── .env                    # Local environment variables (not in git)
├── etl_pipeline.log        # Auto-generated log file
├── tests/
│   └── test_etl.py         # Unit tests for validation and parsing
├── .github/
│   └── workflows/
│       └── etl.yml         # Hourly GitHub Actions schedule
├── Dockerfile              # Container image definition
└── README.md               # This file
```

---

## 👤 Built by
**Jacopo Fornesi** — [🐙 GitHub](https://github.com/Jfor12) | [💼 LinkedIn](https://linkedin.com/in/jacopofornesi)

