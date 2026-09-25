# National Grid Telemetry Pipeline

An hourly pipeline that records how clean Great Britain's electricity is (carbon intensity in gCO₂/kWh) and where it comes from (the generation mix). It also forecasts the next 24 hours with Amazon's Chronos-Bolt model and scores every forecast against what actually happened.

**Dashboard:** [Looker Studio report](https://lookerstudio.google.com/reporting/87673644-a8f6-44f0-b47e-faf9a56704a9)

```mermaid
flowchart LR
    API[Carbon Intensity API] -->|hourly, last 24 h| ETL[etl_job.py<br>GitHub Actions]
    ETL --> T[(grid_telemetry<br>Supabase Postgres)]
    T -->|every 3 h, last 14 days| F[forecast.py<br>Chronos-Bolt]
    F --> P[(grid_predictions)]
    T --> V[SQL views]
    P --> V
    V --> L[Looker Studio]
```

## How it works

**Collection** (`etl_job.py`, hourly). The [Carbon Intensity API](https://carbon-intensity.github.io/api-definitions/) publishes data every half hour. Each run:
- Fetches the last 24 hours of intensity and generation mix.
- Validates every half-hour reading. Readings with a malformed time window, a value out of range, or a mix that doesn't add up to about 100% are rejected and counted.
- Stores one row per hour: the average of that hour's two readings.

Every run re-reads the previous 24 hours, so a run GitHub delays or skips leaves no gap. An hour stored from a forecast is updated when the measured value is published.

Reruns are safe, for two reasons. Rows are upserted on a unique hour, so nothing is duplicated. A row is also never replaced by one built from fewer readings.

Backfills (`--days`) save each day as soon as it is fetched, in a single database round trip. If the API keeps failing on one day, that day is skipped and listed in `etl_runs`, and the run shows red. Everything else is kept, and a rerun fills in the gap.

**Forecasting** (`forecast.py`, every 3 hours). It works on the latest complete hour:
- Takes the last 14 days of carbon intensity and the wind, solar, gas and nuclear shares.
- Forecasts the next 24 hours of each with [`amazon/chronos-bolt-small`](https://huggingface.co/amazon/chronos-bolt-small), a pretrained time-series model that runs on the Actions CPU.
- Stores the median as `predicted_value`, and the 10th and 90th percentiles as `predicted_low` and `predicted_high` (an 80% prediction interval).

It refuses to forecast from stale or thin history rather than store a bad forecast.

**Evaluation** (`sql/views.sql`):
- `forecast_accuracy` lines each forecast up with the actual value.
- It also includes a naive baseline: the value 24 hours earlier, which is hard to beat for a daily-cycle series.
- `forecast_skill` summarises each metric: mean absolute error for the model and the baseline, skill (above 0 means the model beats the baseline), and how often the actual value fell inside the 80% interval.

**Monitoring**:
- Every run of either job writes a row to `etl_runs`: job, status, rows inserted, updated and rejected, duration, and the full traceback on failure.
- A failed run exits non-zero, so it shows red in GitHub Actions and GitHub notifies you.
- The ETL log is uploaded as an artifact when a run fails.

## Data model

All schema changes live in `sql/schema.sql`. They are idempotent, applied at the start of each run, and only ever add columns, so existing queries and dashboards keep working.

| Table / view | What it holds |
|---|---|
| `grid_telemetry` | One row per hour: `overall_intensity` plus National Grid's own `intensity_forecast`, whether the value is measured (`intensity_is_actual`), and the share of each of gas, coal, nuclear, wind, solar, hydro, biomass, imports and other. |
| `grid_predictions` | Forecasts, with `model`, `forecast_origin` and the 80% interval. Rows with no `model` came from an earlier Edge Function (see below). |
| `etl_runs` | One row per run of either job. |
| `grid_mix_hourly` | The hourly mix with renewables, fossil and a coverage check. |
| `forecast_accuracy`, `forecast_skill` | Forecast evaluation, as above. |

## Running it

```bash
pip install -r requirements.txt
export DATABASE_URL='postgresql://…'     # Supabase: use the connection pooler string

python etl_job.py --dry-run               # fetch and validate only
python etl_job.py                         # load the last 24 hours
python etl_job.py --days 30               # backfill 30 days

pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-forecast.txt
python forecast.py --smoke                # check the model runs, no database needed
python forecast.py                        # forecast and store
```

Both jobs also run from the Actions tab with **Run workflow**. The ETL has a `days` input for backfilling and a dry-run switch.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest                          # unit tests
TEST_DATABASE_URL='postgresql://postgres:postgres@localhost:5432/test?sslmode=disable' python -m pytest
```

With `TEST_DATABASE_URL` set, the database tests run against a real Postgres. They start from the tables as they were before the current schema, and cover the upgrade, the upserts, failure logging, backfilling, forecasting and the accuracy views.

CI (`.github/workflows/ci.yml`) runs three jobs on every push and pull request:
- all the tests, against a Postgres service;
- a dry run against the live API, to catch format changes;
- a smoke test that downloads and runs the forecasting model.

## History and known limitations

- **The earlier forecasts weren't real.** Until September 2026, forecasts came from a Supabase Edge Function triggered on every insert. Its Hugging Face token variable was never defined, so every call failed and it fell back to an average, plus a sine wave, plus random noise. Those rows have no `model` value, and the accuracy views ignore them.
- **Older hours aren't comparable.** Hours stored by the earlier version only recorded gas, nuclear, wind and solar, and sometimes a single half-hour reading. Running a backfill (`--days`) rewrites any period with the full mix; the API serves history going back years.
- **Intensity is the national figure** for Great Britain; regional data isn't collected.
