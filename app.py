import streamlit as st
import psycopg
import os

# --- 1. SAFE SECRET LOADING ---
# This ensures the app doesn't crash if 'python-dotenv' is missing
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
# ------------------------------

# 2. Page Configuration
st.set_page_config(page_title="Flight Tracker", page_icon="✈️", layout="centered")
st.title("✈️ Flight Price Tracker")

# 3. Database Connection Helper
def get_connection():
    # If DATABASE_URL is missing, this will fail gracefully later
    return psycopg.connect(os.getenv('DATABASE_URL'), sslmode='require')

# 4. Helper Function: Delete a Route
def delete_route(route_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tracked_routes WHERE id = %s", (route_id,))
                conn.commit()
        st.toast("✅ Route deleted successfully!")
        st.rerun() 
    except Exception as e:
        st.error(f"Error deleting route: {e}")

# --- SECTION 1: ADD NEW ROUTE ---
st.container()
st.subheader("Add a New Trip")

with st.form("add_route_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    
    with col1:
        origin = st.text_input("From (e.g. LHR)", value="LON").upper()
        date_out = st.date_input("Departure Date")
        
    with col2:
        dest = st.text_input("To (e.g. JFK)", value="JFK").upper()
        date_ret = st.date_input("Return (Optional)", value=None)

    submitted = st.form_submit_button("Start Tracking 🚀")

    if submitted:
        if not origin or not dest:
            st.error("Please fill in Origin and Destination.")
        else:
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO tracked_routes (origin_code, dest_code, flight_date, return_date)
                            VALUES (%s, %s, %s, %s)
                        """, (origin, dest, date_out, date_ret))
                        conn.commit()
                st.success(f"Now tracking {origin} -> {dest}!")
                st.rerun()
            except Exception as e:
                st.error(f"Database Error: {e}")

# --- SECTION 2: MANAGE ROUTES ---
st.divider()
st.subheader("Your Wishlist")

try:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, origin_code, dest_code, flight_date, return_date 
                FROM tracked_routes 
                ORDER BY flight_date ASC
            """)
            rows = cur.fetchall()

            if not rows:
                st.info("You aren't tracking any flights yet.")
            else:
                # Table Headers
                h1, h2, h3, h4 = st.columns([2, 2, 1, 1])
                h1.markdown("**Route**")
                h2.markdown("**Dates**")
                h3.markdown("**Link**")
                h4.markdown("**Action**")
                
                for row in rows:
                    r_id, r_orig, r_dest, r_out, r_ret = row
                    
                    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                    
                    # 1. Route
                    c1.write(f"**{r_orig} ➝ {r_dest}**")
                    
                    # 2. Dates
                    if r_ret:
                        c2.write(f"{r_out} to {r_ret}")
                    else:
                        c2.write(f"{r_out} (One way)")
                        
                    # 3. Generate Skyscanner Link
                    out_str = str(r_out).replace("-", "")[2:]
                    if r_ret:
                        ret_str = str(r_ret).replace("-", "")[2:]
                        url = f"https://www.skyscanner.net/transport/flights/{r_orig}/{r_dest}/{out_str}/{ret_str}"
                    else:
                        url = f"https://www.skyscanner.net/transport/flights/{r_orig}/{r_dest}/{out_str}"
                    
                    c3.link_button("🔗", url, help="Check on Skyscanner")

                    # 4. Delete Button
                    if c4.button("🗑️", key=f"del_{r_id}"):
                        delete_route(r_id)
                    
                    st.divider()

except Exception as e:
    # This catches errors if DATABASE_URL is missing or wrong
    st.error(f"Connection Error: {e}")