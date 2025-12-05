# ✈️ Flight Price Tracker & ETL

A lightweight data pipeline and dashboard to track flight prices for routes you care about. Use the Streamlit app to manage a wishlist of routes and an ETL job (scheduled via GitHub Actions or run locally) to fetch daily flight offers from the Amadeus API and store raw results in PostgreSQL.

**Key ideas:**
- Manage tracked routes (origin, destination, dates) via a Streamlit UI.
- Daily ETL job queries Amadeus for flight offers and saves raw JSON to the DB.
- Quick Skyscanner booking links are generated for each tracked route.

---

## 🌟 Features
- Wishlist management: add, remove, and list tracked routes from the UI.
- Automated ETL: `etl_job.py` fetches offers and stores raw responses in `raw_flights`.
- Skyscanner quick links for each route.
- Graceful handling of missing API keys, empty API results, and DB errors.
- Configurable via environment variables and GitHub Secrets for CI runs.

---

## 🛠️ Tech Stack
- Python 3.9+
- Streamlit (frontend)
- PostgreSQL (database) via `psycopg` v3
- Amadeus Flight Offers Search API (`amadeus` Python client)
- GitHub Actions for scheduled ETL runs

---

## 🚀 Quick Start (Local)

1. Clone the repository:

```bash
git clone https://github.com/Jfor12/flight-data-pipeline.git
cd flight-data-pipeline
```

2. Create and activate a Python virtual environment (optional but recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root (for local development) with the following variables:

```env
DATABASE_URL=postgresql://user:password@host:port/dbname
AMADEUS_KEY=your_amadeus_api_key
AMADEUS_SECRET=your_amadeus_api_secret
# Optional when running in an environment that provides these already
```

5. Apply the database schema (example SQL below) to create the required tables in PostgreSQL.

6. Run the Streamlit app:

```bash
streamlit run app.py
```

7. Run the ETL job manually (or rely on scheduled CI runs):

```bash
python etl_job.py
```

---

## 📦 Database schema (example)
Run these SQL statements in your PostgreSQL database to create the minimal tables expected by the project:

```sql
CREATE TABLE tracked_routes (
  id SERIAL PRIMARY KEY,
  origin_code VARCHAR(8) NOT NULL,
  dest_code VARCHAR(8) NOT NULL,
  flight_date DATE NOT NULL,
  return_date DATE
);

CREATE TABLE raw_flights (
  id SERIAL PRIMARY KEY,
  origin_code VARCHAR(8) NOT NULL,
  dest_code VARCHAR(8) NOT NULL,
  flight_date DATE NOT NULL,
  raw_response JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

Adjust types/constraints to match your production needs.

---

## 🔑 Environment Variables / Secrets
- `DATABASE_URL` — full Postgres connection string used by `psycopg` (required).
- `AMADEUS_KEY` and `AMADEUS_SECRET` — credentials for the Amadeus API (required for ETL).

In CI (GitHub Actions), set these as repository/project secrets. Locally, use a `.env` file and `python-dotenv` will load it.

---

## ▶️ How it works
- `app.py` provides a Streamlit UI to add routes to `tracked_routes` and to list/delete them. It generates Skyscanner links for quick manual checks.
- `etl_job.py` loads tracked routes from the DB, calls the Amadeus Flight Offers Search API for each route, and inserts the raw JSON results into `raw_flights`.
- The project is designed so the ETL job can run periodically (e.g., daily at 08:00 UTC) via GitHub Actions.

---

## 🔁 GitHub Actions (scheduled ETL)
Add a workflow that runs `python etl_job.py` on a daily cron schedule. Ensure the secrets `DATABASE_URL`, `AMADEUS_KEY`, and `AMADEUS_SECRET` are configured in the repository settings.

---

## 🧰 Troubleshooting
- Missing API keys: `etl_job.py` prints a configuration check and exits if `AMADEUS_KEY`/`AMADEUS_SECRET` are not set.
- Database errors: make sure `DATABASE_URL` is correct and the tables exist. The Streamlit app and ETL job print error messages and rollback on DB exceptions.
- Empty API results: the ETL prints warnings when Amadeus returns no offers (this can happen in sandbox/test accounts).

---

## ✅ Tips & Next Steps
- Add validation and duplication checks for routes in `app.py`.
- Add a lightweight frontend view to visualize price history by parsing `raw_flights`.
- Add alerting (email/Slack) when prices meet a desired threshold.

---

## 👥 Contributing
Contributions are welcome. Please open issues or pull requests for enhancements or bug fixes.

---

## 📄 License
This project is provided as-is. Add a license file as needed for your project.

---

If you'd like, I can also add a simple GitHub Actions workflow sample and update `requirements.txt` to reflect the exact dependencies used here.
