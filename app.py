import streamlit as st
import streamlit.components.v1 as components
import psycopg
import os
from datetime import date

# 1. SAFE SECRET LOADING
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 2. PAGE CONFIG
st.set_page_config(
    page_title="Flight Price Tracker", 
    page_icon="✈️", 
    layout="wide", # Keeps it wide, but we will center content manually
    initial_sidebar_state="expanded"
)

# --- CONSTANTS ---
AIRPORT_LIST = {
    "LHR": "London Heathrow (UK)",
    "LGW": "London Gatwick (UK)",
    "JFK": "New York JFK (USA)",
    "LAX": "Los Angeles (USA)",
    "DXB": "Dubai (UAE)",
    "CDG": "Paris Charles de Gaulle (France)",
    "AMS": "Amsterdam Schiphol (Netherlands)",
    "FRA": "Frankfurt (Germany)",
    "SIN": "Singapore Changi (Singapore)",
    "SYD": "Sydney (Australia)",
    "YYZ": "Toronto Pearson (Canada)",
    "HKG": "Hong Kong (China)",
    "MAD": "Madrid (Spain)",
    "FCO": "Rome Fiumicino (Italy)",
    "IST": "Istanbul (Turkey)",
    "BKK": "Bangkok (Thailand)"
}

def format_airport(code):
    return f"{code} - {AIRPORT_LIST[code]}"

# 3. DB CONNECTION
def get_connection():
    return psycopg.connect(os.getenv('DATABASE_URL'), sslmode='require')

# 4. DELETE HELPER
def delete_route(route_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tracked_routes WHERE id = %s", (route_id,))
                conn.commit()
        st.toast("✅ Route deleted successfully!", icon="🗑️")
        st.rerun() 
    except Exception as e:
        st.error(f"Error: {e}")

# --- SIDEBAR ---
with st.sidebar:
    st.header("✈️ Flight Tracker")
    
    # Get latest update time
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(ingested_at) FROM raw_flights")
                last_update = cur.fetchone()[0]
        last_update_str = last_update.strftime("%Y-%m-%d %H:%M:%S") if last_update else "Never"
    except:
        last_update_str = "N/A"
    
    st.markdown(f"""
    **Status:** 🟢 Online  
    **Update Frequency:** Daily at 8:00 AM UTC  
    **Last Update:** {last_update_str}
    """)
    st.divider()
    st.info("💡 **Prices are simulated via Amadeus API**\n\nThis app uses the Amadeus testing environment. Displayed prices are not real-time and for demonstration purposes only.")
    
    # Signature Section
    st.divider()
    st.markdown("""
    ---
    **Built by Jfor12**
    
    [🐙 GitHub](https://github.com/Jfor12) | [💼 LinkedIn](https://linkedin.com/in/jacopofornesi) | [📧 Email](mailto:jacopofornesi@hotmail.com)
    """)

# --- MAIN LAYOUT ---

# CENTERED HEADER
c1, c2, c3 = st.columns([1, 6, 1])
with c2:
    st.title("🌍 Flight Price Intelligence")
    st.markdown("Monitor global flight prices and get direct booking links.")

st.markdown("---")

# --- TABS ---
tab1, tab2 = st.tabs(["📝 Manage Watchlist", "📊 Price Analytics"])

# ==========================================
# TAB 1: MANAGE ROUTES
# ==========================================
with tab1:
    # CENTERED CONTENT BLOCK
    # We use columns [1, 4, 1] to squeeze the content into the center
    spacer_l, main_content, spacer_r = st.columns([1, 4, 1])
    
    with main_content:
        # 2. ADD ROUTE FORM
        with st.expander("➕ Add a New Route", expanded=True):
            with st.form("add_route_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    origin = st.selectbox("Origin", options=AIRPORT_LIST.keys(), format_func=format_airport)
                    date_out = st.date_input("Departure", min_value=date.today())
                with c2:
                    dest = st.selectbox("Destination", options=AIRPORT_LIST.keys(), format_func=format_airport, index=2)
                    date_ret = st.date_input("Return (Optional)", value=None, min_value=date.today())
                
                submitted = st.form_submit_button("Start Tracking 🚀", type="primary", use_container_width=True)

                if submitted:
                    if origin == dest:
                        st.error("❌ Origin and Destination cannot be the same!")
                    elif date_ret and date_ret < date_out:
                        st.error("❌ Return Date cannot be before Departure!")
                    else:
                        try:
                            with get_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        INSERT INTO tracked_routes (origin_code, dest_code, flight_date, return_date)
                                        VALUES (%s, %s, %s, %s)
                                    """, (origin, dest, date_out, date_ret))
                                    conn.commit()
                            st.success(f"✅ Added {origin} -> {dest}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        # 3. EXISTING ROUTES
        st.subheader("Your Watchlist")
        
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
                        for row in rows:
                            r_id, r_orig, r_dest, r_out, r_ret = row
                            
                            with st.container(border=True):
                                c1, c2, c3, c4 = st.columns([2, 3, 2, 2])
                                c1.markdown(f"**{r_orig} ✈️ {r_dest}**")
                                if r_ret:
                                    c2.text(f"{r_out} ➡ {r_ret}")
                                else:
                                    c2.text(f"{r_out}")
                                
                                # Link
                                out_str = str(r_out).replace("-", "")[2:]
                                url = f"https://www.skyscanner.net/transport/flights/{r_orig}/{r_dest}/{out_str}"
                                if r_ret:
                                    ret_str = str(r_ret).replace("-", "")[2:]
                                    url += f"/{ret_str}"
                                c3.link_button("Book 🔗", url)
                                
                                if c4.button("Remove", key=f"del_{r_id}"):
                                    delete_route(r_id)

        except Exception as e:
            st.error(f"Error: {e}")

# ==========================================
# TAB 2: ANALYTICS (Centered)
# ==========================================
with tab2:
    # CENTERED IFRAME TRICK
    # We create 3 columns: [Spacer, Content, Spacer]
    # The middle column is 10x wider than the spacers, effectively centering it
    space_left, content, space_right = st.columns([1, 10, 1])
    
    with content:
        st.info("💡 Interactive Dashboard loaded from Google Looker Studio")
        
        # REPLACE THIS WITH YOUR LOOKER URL
        LOOKER_URL = "https://lookerstudio.google.com/embed/reporting/17d54e78-beda-4a69-b965-c3a95cf9848f/page/Yz2hF"
        
        # Use scrolling=True so users can move around the dashboard if it's large
        components.iframe(LOOKER_URL, height=900, scrolling=True)