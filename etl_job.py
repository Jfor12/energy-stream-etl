import os
import json
import psycopg
from amadeus import Client, ResponseError

# 1. LOAD SECRETS
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- DEBUG: CHECK KEYS BEFORE STARTING ---
AMADEUS_KEY = os.getenv('AMADEUS_KEY')
AMADEUS_SECRET = os.getenv('AMADEUS_SECRET')
DB_URL = os.getenv('DATABASE_URL')

print("--- CONFIGURATION CHECK ---")
print(f"1. Key Found:    {'✅ Yes' if AMADEUS_KEY else '❌ NO (Script will crash)'}")
print(f"2. Secret Found: {'✅ Yes' if AMADEUS_SECRET else '❌ NO (Script will crash)'}")
print(f"3. Database URL: {'✅ Yes' if DB_URL else '❌ NO'}")
print("---------------------------")

if not AMADEUS_KEY or not AMADEUS_SECRET:
    print("❌ CRITICAL ERROR: API Keys are missing. Stopping now.")
    exit(1)
# -----------------------------------------

# 2. INITIALIZE CLIENT
amadeus = Client(
    client_id=AMADEUS_KEY,
    client_secret=AMADEUS_SECRET
)

def run_pipeline():
    if not DB_URL:
        print("❌ CRITICAL ERROR: Database URL is missing.")
        return

    with psycopg.connect(DB_URL, sslmode='require') as conn:
        with conn.cursor() as cursor:
            
            # 1. FETCH ROUTES
            print("Fetching wishlist from database...")
            cursor.execute("SELECT origin_code, dest_code, flight_date, return_date FROM tracked_routes")
            db_routes = cursor.fetchall()
            
            if not db_routes:
                print("No routes found in database.")
                return

            # 2. PROCESS EACH ROUTE
            for r in db_routes:
                origin, dest, date_obj, return_date_obj = r
                date_str = str(date_obj)
                
                try:
                    # --- IMPROVED PRINT STATEMENT ---
                    if return_date_obj:
                        print(f"\n🔎 Checking {origin} -> {dest} | Dep: {date_str} | Ret: {return_date_obj}")
                    else:
                        print(f"\n🔎 Checking {origin} -> {dest} | Dep: {date_str} (One way)")
                    
                    # 3. PREPARE API PARAMETERS
                    api_params = {
                        "originLocationCode": origin,
                        "destinationLocationCode": dest,
                        "departureDate": date_str,
                        "adults": 1,
                        "max": 5
                    }

                    if return_date_obj:
                        api_params["returnDate"] = str(return_date_obj)

                    # --- DEBUG: PRINT EXACTLY WHAT WE SEND ---
                    print(f"   📤 Sending to API: {json.dumps(api_params)}")

                    # 4. CALL API
                    response = amadeus.shopping.flight_offers_search.get(**api_params)
                    
                    # 5. CHECK FOR EMPTY DATA (Test Env Limitation)
                    if not response.data:
                        print(f"   ⚠️  Amadeus returned 0 flights.")
                        print(f"   ℹ️  Reason: {response.result.get('meta', {}).get('count', 'Unknown')}")
                    
                    # 6. SAVE DATA
                    data_json = json.dumps(response.data)
                    query = """
                        INSERT INTO raw_flights (origin_code, dest_code, flight_date, raw_response)
                        VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(query, (origin, dest, date_str, data_json))
                    conn.commit()
                    print(f"   ✅ Success! Saved to DB.")

                except ResponseError as error:
                    print(f"   ❌ API Error: {error}")
                    print(f"   ℹ️  (If this is 401, your keys are invalid/expired)")
                except Exception as e:
                    print(f"   ❌ Database Error: {e}")
                    conn.rollback() 

if __name__ == "__main__":
    run_pipeline()