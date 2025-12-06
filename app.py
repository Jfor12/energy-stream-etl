import streamlit as st
import streamlit.components.v1 as components # Required for embedding
import psycopg
import os

# 1. SAFE SECRET LOADING
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 2. Page Config (Wide mode looks better for Dashboards)
st.set_page_config(page_title="Flight Tracker", page_icon="✈️", layout="wide")
st.title("✈️ Flight Price Tracker")

# 3. DB Connection
def get_connection():
    return psycopg.connect(os.getenv('DATABASE_URL'), sslmode='require')

# 4. Delete Helper
def delete_route(route_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tracked_routes WHERE id = %s", (route_id,))
                conn.commit()
        st.toast("✅ Route deleted!")
        st.rerun() 
    except Exception as e:
        st.error(f"Error: {e}")

# --- TABS CONFIGURATION ---
tab1, tab2 = st.tabs(["📝 Manage Flights", "📊 Price Analytics"])

# ==========================================
# TAB 1: MANAGE ROUTES (Your existing logic)
# ==========================================
with tab1:
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
                st.error("Missing Origin/Dest")
            else:
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO tracked_routes (origin_code, dest_code, flight_date, return_date)
                                VALUES (%s, %s, %s, %s)
                            """, (origin, dest, date_out, date_ret))
                            conn.commit()
                    st.success(f"Added {origin}->{dest}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Error: {e}")

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
                    st.info("No routes yet.")
                else:
                    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                    c1.markdown("**Route**")
                    c2.markdown("**Dates**")
                    c3.markdown("**Link**")
                    c4.markdown("**Action**")
                    
                    for row in rows:
                        r_id, r_orig, r_dest, r_out, r_ret = row
                        
                        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                        
                        # 1. Route
                        c1.write(f"**{r_orig} ➝ {r_dest}**")
                        
                        # 2. Dates
                        if r_ret:
                            c2.write(f"{r_out} to {r_ret}")
                        else:
                            c2.write(f"{r_out}")
                            
                        # 3. Skyscanner Link
                        out_str = str(r_out).replace("-", "")[2:]
                        url = f"https://www.skyscanner.net/transport/flights/{r_orig}/{r_dest}/{out_str}"
                        if r_ret:
                            ret_str = str(r_ret).replace("-", "")[2:]
                            url += f"/{ret_str}"
                        
                        c3.link_button("🔗", url)

                        # 4. Delete
                        if c4.button("🗑️", key=f"del_{r_id}"):
                            delete_route(r_id)
                        
                        st.divider()

    except Exception as e:
        st.error(f"Error: {e}")

# ==========================================
# TAB 2: PRICE ANALYTICS (Looker Studio)
# ==========================================
with tab2:
    st.header("Price Trends")
    
    # ⚠️ REPLACE THIS LINK WITH YOUR LOOKER STUDIO EMBED URL
    LOOKER_URL = "https://lookerstudio.google.com/embed/reporting/17d54e78-beda-4a69-b965-c3a95cf9848f/page/Yz2hF"
    
    # Embed the dashboard
    # Adjust height to ensure the whole dashboard fits without scrolling
    components.iframe(LOOKER_URL, width=1000, height=800)