
# ⚡ National Grid Telemetry Pipeline

An automated data engineering pipeline for monitoring and analysing National Grid carbon intensity in real time. Ingests live generation mix (solar, wind, gas, nuclear) and archives telemetry for historical analysis.

## Features
- Automated ETL: Hourly GitHub Actions job (free)
- Structured logging with timestamps
- Exponential backoff for API failures
- Data quality checks (null, type, range)
- Duplicate prevention (hourly, normalised timestamps)
- ETL metadata tracking
- Unit tested (pytest)
- Postgres-first: Schema for Supabase or any managed Postgres
- Predictive analytics: 24-hour and 7-day forecasting
- Accuracy tracking: Real vs forecasted comparisons

## Tech Stack
- Python 3.9+
- PostgreSQL (via psycopg v3)
- Requests (National Grid ESO API)
- GitHub Actions (hourly schedule)
- Supabase (database, Edge Functions)
- Hugging Face (AI forecasting)

## Quick Start
1. Clone and install dependencies
   ```bash
   git clone <your-repo-url>
   cd energy-stream-etl
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Set environment
   Create a `.env` file:
   ```env
   DATABASE_URL=postgresql://user:password@host:port/dbname
   ```
3. Create the tables (see schema below)
4. Run the ETL once
   ```bash
   python etl_job.py
   ```
5. Deploy to GitHub Actions for free hourly runs (add `DATABASE_URL` as a secret)

## Database Schema
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

## Analytics (SQL Views)
Time-windowed views for easier visualisation and analysis:
- `grid_predictions_24h` — Last 24 hours of grid predictions
- `grid_predictions_7d` — Last 7 days of grid predictions
- `actual_vs_predicted_24h` — Last 24 hours of actual vs predicted
- `actual_vs_predicted_7d` — Last 7 days of actual vs predicted
- `grid_telemetry_7d` — Last 7 days of grid telemetry

**Example queries:**
```sql
SELECT * FROM grid_predictions_24h ORDER BY prediction_timestamp DESC LIMIT 20;
SELECT * FROM grid_predictions_7d ORDER BY prediction_timestamp DESC LIMIT 20;
SELECT * FROM actual_vs_predicted_24h ORDER BY actual_timestamp DESC LIMIT 20;
SELECT * FROM actual_vs_predicted_7d ORDER BY actual_timestamp DESC LIMIT 20;
SELECT * FROM grid_telemetry_7d ORDER BY timestamp DESC LIMIT 20;
```

## Supabase Edge Function (Forecasting)
- Automated forecasting using Hugging Face AI and statistical models
- Normalises all prediction timestamps to the top of the hour
- Stores 24-hour forecasts for all metrics

## Environment Variables
- `DATABASE_URL` — Postgres connection string (required)
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` — for Supabase integration
- `HF_TOKEN` — Hugging Face API token

## Testing
Run unit tests:
```bash
pytest tests/test_etl.py -v
```

## Troubleshooting
- Check `etl_pipeline.log` for errors
- Ensure all environment variables are set
- For Supabase/Edge Function issues, check Supabase logs and secrets

## Project Structure
```
energy-stream-etl/
├── etl_job.py
├── requirements.txt
├── tests/
│   └── test_etl.py
├── .github/
│   └── workflows/
│       └── etl.yml
├── docs/
│   └── GITHUB_ACTIONS_SETUP.md
├── README.md

## Author
Jacopo Fornesi — [GitHub](https://github.com/Jfor12) | [LinkedIn](https://linkedin.com/in/jacopofornesi)

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

#### Time-windowed Views for Visualization

To make visualisation and analysis easier, the following SQL views are available:

- `grid_predictions_24h` — Last 24 hours of grid predictions
- `grid_predictions_7d` — Last 7 days of grid predictions
- `actual_vs_predicted_24h` — Last 24 hours of actual vs predicted data
- `actual_vs_predicted_7d` — Last 7 days of actual vs predicted data
- `grid_telemetry_7d` — Last 7 days of grid telemetry data

These views are automatically updated and can be queried directly for recent trends and historical analysis.

**Example queries:**

```sql
-- Last 24 hours of grid predictions
SELECT * FROM grid_predictions_24h ORDER BY prediction_timestamp DESC LIMIT 20;

-- Last 7 days of grid predictions
SELECT * FROM grid_predictions_7d ORDER BY prediction_timestamp DESC LIMIT 20;

-- Last 24 hours of actual vs predicted
SELECT * FROM actual_vs_predicted_24h ORDER BY actual_timestamp DESC LIMIT 20;

-- Last 7 days of actual vs predicted
SELECT * FROM actual_vs_predicted_7d ORDER BY actual_timestamp DESC LIMIT 20;

-- Last 7 days of grid telemetry
SELECT * FROM grid_telemetry_7d ORDER BY timestamp DESC LIMIT 20;
```

#### Daily Cleanliness View
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

