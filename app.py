import streamlit as st
import psycopg
import os
from dotenv import load_dotenv

# Load secrets
load_dotenv()

# Page Config
st.set_page_config(page_title="Flight Tracker", page_icon="✈️")
st.title("✈️ Flight Price Tracker")

# --- DATABASE CONNECTION ---
def get_connection():
    return psycopg.connect(os.getenv('DATABASE_URL'), sslmode='require')

# --- SECTION 1: ADD NEW ROUTE ---
st.header("Add a Route to Track")

with st.form("route_form"):
    col1, col2 = st.columns(2)
    with col1:
        origin = st.text_input("Origin Code (e.g., LON)", value="LON").upper()
        date_out = st.date_input("Departure Date")
    with col2:
        dest = st.text_input("Destination Code (e.g., PSA)", value="PSA").upper()
        date_ret = st.date_input("Return Date (Optional)", value=None)

    submitted = st.form_submit_button("Start Tracking")

    if submitted:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO tracked_routes (origin_code, dest_code, flight_date, return_date)
                        VALUES (%s, %s, %s, %s)
                    """, (origin, dest, date_out, date_ret))
                    conn.commit()
            st.success(f"✅ Now tracking {origin} -> {dest} for {date_out}")
        except Exception as e:
            st.error(f"Error saving to DB: {e}")

# --- SECTION 2: SHOW TRACKED ROUTES ---
st.divider()
st.subheader("Currently Tracking")

try:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT origin_code, dest_code, flight_date, return_date FROM tracked_routes")
            rows = cur.fetchall()
            
            if rows:
                # Convert to a nice table
                st.table([
                    {"Origin": r[0], "Dest": r[1], "Outbound": r[2], "Return": r[3]} 
                    for r in rows
                ])
            else:
                st.info("No routes being tracked yet.")
except Exception as e:
    st.error(f"Error reading DB: {e}")