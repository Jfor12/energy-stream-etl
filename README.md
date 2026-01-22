# National Grid Telemetry Pipeline

Production-style ETL + analytics views for a dashboard tracking UK grid carbon intensity and generation mix, with optional AI-driven forecasts via Supabase.

## What I Built

- Python ETL (etl_job.py) that ingests National Grid ESO data and stores hourly telemetry in Postgres
- Reliability + data quality: retries with exponential backoff, validation, structured logging
- Operational metadata: etl_runs records status, rows inserted, runtime, and errors
- Dashboard-ready views to compare actuals vs forecasts and measure prediction error (24h)
- Automation: GitHub Actions schedule (every 30 minutes)

## Dashboard

- Live dashboard: https://lookerstudio.google.com/reporting/17d54e78-beda-4a69-b965-c3a95cf9848f

## Architecture

```mermaid
flowchart TD
  A[GitHub Actions schedule\n(every 30 min)] --> B[etl_job.py\nFetch + validate + normalize]
  B --> C[(Postgres / Supabase)]
  C --> D[grid_telemetry]
  D --> E[Views for dashboard\nactual_vs_predicted_24h\nerror_rate_24h]
  E --> F[Dashboard]

  D -->|optional webhook| G[Supabase Edge Function\nforecasting]
  G --> H[Hugging Face Chronos\n(time-series model)]
  H --> I[grid_predictions]
  I --> E
```

## Supabase + AI Forecasting (Optional)

If you enable forecasting:

1. The ETL inserts telemetry into grid_telemetry
2. A Supabase Database Webhook triggers an Edge Function
3. The function calls an AI time-series model (Hugging Face Chronos)
4. Forecasts are upserted into grid_predictions
5. The dashboard queries views like actual_vs_predicted_24h and error_rate_24h

Recommended secrets (Supabase): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, HF_TOKEN.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create .env:

```env
DATABASE_URL=postgresql://user:password@host:port/dbname
```

Run:

```bash
python etl_job.py
```

## Tests

```bash
pytest tests/test_etl.py -v
```

## Repo Structure

```text
energy-stream-etl/
  etl_job.py
  requirements.txt
  tests/
    test_etl.py
  .github/
    workflows/
      etl.yml
```

## Author

Jacopo Fornesi

- GitHub: https://github.com/Jfor12
- LinkedIn: https://linkedin.com/in/jacopofornesi
