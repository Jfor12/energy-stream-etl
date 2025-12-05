# ✈️ The Flight Deal Hunter: Automated ELT Pipeline

**A serverless data pipeline that tracks flight prices daily to find the best time to fly.**

[![Run Pipeline](https://github.com/YOUR_USERNAME/flight-tracker/actions/workflows/daily_run.yml/badge.svg)](https://github.com/YOUR_USERNAME/flight-tracker/actions)
![Python](https://img.shields.io/badge/Python-3.9-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-green)

## 🏗 Architecture
[Insert Diagram Here - See Section 2 below]
* **Extraction:** Python script hits Amadeus API to fetch prices for watched routes.
* **Loading:** Raw JSON data is dumped into **Supabase (PostgreSQL)** for auditability.
* **Transformation:** Data is parsed from JSONB into structured tables for analysis.
* **Orchestration:** **GitHub Actions** runs the containerized script every morning at 08:00 UTC.
* **Visualization:** **Streamlit** dashboard allows users to add routes and view trends.

## 🚀 How to Run Locally
1. Clone the repo
2. Create a `.env` file with your API keys
3. Run `pip install -r requirements.txt`
4. Run `streamlit run app.py`

## 💡 What I Learned
* How to handle **JSONB** data in PostgreSQL to allow flexible schema changes.
* Implementing **SSL/TLS** security for database connections in Python.
* Automating workflows with **CI/CD** (GitHub Actions) instead of local Cron jobs.