# ✈️ Flight Price Tracker & ETL

A lightweight data pipeline and dashboard to track flight prices for routes you care about. Use the Streamlit app to manage a watchlist of routes and an ETL job (scheduled via GitHub Actions or run locally) to fetch daily flight offers from the Amadeus API and store raw results in PostgreSQL.

**Key Features:**
- **Intuitive UI**: Manage tracked routes (origin, destination, dates) with a modern blue-themed Streamlit interface.
- **Automated ETL**: Daily job fetches flight offers from Amadeus and stores raw JSON responses in PostgreSQL.
- **Quick Booking Links**: Direct Skyscanner links for each tracked route.
- **Real-time Updates**: Sidebar displays the latest data ingestion timestamp.
- **Interactive Analytics**: Google Looker Studio dashboard integration for price analysis.
- **Robust Error Handling**: Graceful management of API errors, empty results, and database issues.

---

## 🌟 Features
- ✅ Watchlist management: add, view, and delete tracked routes from the UI.
- ✅ Automated daily ETL: fetches flight offers and stores raw API responses.
- ✅ Direct booking links: one-click access to Skyscanner for each route.
- ✅ Live status indicator: displays online status, update frequency, and last data ingestion time.
- ✅ Price analytics dashboard: integrated Google Looker Studio for visualizing trends.
- ✅ Professional blue theme: clean, modern UI design.
- ✅ Test environment warning: clearly indicates simulated pricing data.
- ✅ Developer credits: GitHub, LinkedIn, and email links in the sidebar.

---

## 🛠️ Tech Stack
- Python 3.9+
- Streamlit (frontend with custom CSS styling)
- PostgreSQL (database) via `psycopg` v3
- Amadeus Flight Offers Search API (`amadeus` Python client)
- Google Looker Studio (analytics dashboard)
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
```

5. Apply the database schema (example SQL below) to create the required tables in PostgreSQL.

6. Run the Streamlit app:

```bash
streamlit run app.py
```

The app will launch at `http://localhost:8501`.

7. Run the ETL job manually (or rely on scheduled CI runs):

```bash
python etl_job.py
```

---

## 📦 Database Schema
Run these SQL statements in your PostgreSQL database to create the required tables:

```sql
CREATE TABLE public.tracked_routes (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  origin_code text NOT NULL,
  dest_code text NOT NULL,
  flight_date date NOT NULL,
  return_date date,
  created_at timestamp without time zone DEFAULT now(),
  target_price numeric,
  CONSTRAINT tracked_routes_pkey PRIMARY KEY (id)
);

CREATE TABLE public.raw_flights (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  ingested_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
  origin_code text,
  dest_code text,
  flight_date date,
  raw_response jsonb,
  return_date date,
  CONSTRAINT raw_flights_pkey PRIMARY KEY (id)
);

CREATE TABLE public.airport_codes (
  iata_code character NOT NULL,
  city_name text,
  full_name text,
  CONSTRAINT airport_codes_pkey PRIMARY KEY (iata_code)
);

CREATE TABLE public.airline_codes (
  iata_code character NOT NULL,
  airline_name text,
  CONSTRAINT airline_codes_pkey PRIMARY KEY (iata_code)
);
```

### Analytics View for Looker Studio

Create this view to power your Looker Studio dashboard:

```sql
DROP VIEW IF EXISTS view_flight_prices;

CREATE VIEW view_flight_prices AS
SELECT 
    f.id,
    f.ingested_at::date as scrape_date,
    
    -- AIRPORTS (Normalized)
    f.origin_code,
    COALESCE(a1.city_name, f.origin_code) as origin_city,
    f.dest_code,
    COALESCE(a2.city_name, f.dest_code) as dest_city,
    
    f.flight_date,
    f.return_date,
    
    -- PRICE
    (f.raw_response->0->'price'->>'total')::DECIMAL as price,
    f.raw_response->0->'price'->>'currency' as currency,
    
    -- AIRLINE (Normalized)
    (f.raw_response->0->'validatingAirlineCodes'->>0) as airline_code,
    COALESCE(ac.airline_name, (f.raw_response->0->'validatingAirlineCodes'->>0)) as airline_name,

    -- ROUND TRIP CHECK
    CASE 
        WHEN f.return_date IS NOT NULL THEN TRUE 
        ELSE FALSE 
    END as is_round_trip,

    -- DIRECT FLIGHT CHECK
    CASE 
        WHEN f.return_date IS NOT NULL THEN 
            (jsonb_array_length(f.raw_response->0->'itineraries'->0->'segments') = 1 
             AND 
             jsonb_array_length(f.raw_response->0->'itineraries'->1->'segments') = 1)
        ELSE 
            jsonb_array_length(f.raw_response->0->'itineraries'->0->'segments') = 1
    END as is_flight_direct

FROM raw_flights f
LEFT JOIN airport_codes a1 ON f.origin_code = a1.iata_code
LEFT JOIN airport_codes a2 ON f.dest_code = a2.iata_code
LEFT JOIN airline_codes ac ON (f.raw_response->0->'validatingAirlineCodes'->>0) = ac.iata_code
WHERE f.raw_response IS NOT NULL 
  AND jsonb_array_length(f.raw_response) > 0;
```

This view normalizes raw flight data and joins airport/airline reference tables, making it perfect for analytics dashboards.

---

## 🔑 Environment Variables
- `DATABASE_URL` — PostgreSQL connection string (required).
- `AMADEUS_KEY` and `AMADEUS_SECRET` — Amadeus API credentials (required for ETL).

In CI (GitHub Actions), configure these as repository secrets. For local development, use a `.env` file.

---

## ▶️ How It Works

### Streamlit App (`app.py`)
- **Manage Watchlist Tab**: Add new routes with origin/destination airports and travel dates. View, edit, and delete tracked routes. Generate direct Skyscanner booking links.
- **Price Analytics Tab**: Interactive Google Looker Studio dashboard for price trend analysis.
- **Sidebar**: Live status, update frequency, last data ingestion timestamp (from `ingested_at`), and developer information.
- **Blue Theme**: Professional, modern UI with custom CSS styling.

### ETL Job (`etl_job.py`)
- Loads all tracked routes from the database.
- Queries the Amadeus Flight Offers Search API for each route.
- Stores raw API responses as JSON in the `raw_flights` table.
- Avoids duplicate daily scrapes to optimize API calls.
- Prints detailed logs for monitoring and debugging.

### Automated Scheduling
The ETL job is designed to run periodically (e.g., daily at 08:00 UTC) via GitHub Actions or your scheduler of choice.

---

## 🔁 GitHub Actions (Scheduled ETL)
Add a workflow file (`.github/workflows/etl.yml`) to run the ETL job on a schedule:

```yaml
name: Daily Flight Price ETL

on:
  schedule:
    - cron: '0 8 * * *'  # Daily at 08:00 UTC

jobs:
  etl:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - run: pip install -r requirements.txt
      - run: python etl_job.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          AMADEUS_KEY: ${{ secrets.AMADEUS_KEY }}
          AMADEUS_SECRET: ${{ secrets.AMADEUS_SECRET }}
```

---

## 🧰 Troubleshooting
- **Missing API keys**: Both `app.py` and `etl_job.py` validate environment variables and provide clear error messages.
- **Database errors**: Verify `DATABASE_URL` is correct and tables exist. Check database logs for connection issues.
- **Empty API results**: The Amadeus test environment may return no offers for certain routes. This is normal and logged.

---

## ✅ Tips & Next Steps
- **Enhance route management**: Add more validation, favorites, and route templates.
- **Price alerts**: Implement email or Slack notifications when prices drop below a threshold.
- **Historical analysis**: Build advanced analytics views in Looker Studio or export to additional tools.
- **Multi-currency support**: Add currency conversion and display options.
- **Mobile responsive**: Further optimize the UI for mobile devices.

---

## 👥 Contributing
Contributions are welcome! Please open issues or pull requests for enhancements or bug fixes.

---

## 📄 License
This project is provided as-is. Add a license file as needed.

---

## 👤 Built by
**Jfor12** — [🐙 GitHub](https://github.com/Jfor12) | [💼 LinkedIn](https://linkedin.com/in/Jfor12)

If you have questions or suggestions, feel free to reach out or open an issue!

