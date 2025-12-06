import os
import json
import psycopg
from datetime import date
from amadeus import Client, ResponseError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

AMADEUS_KEY = os.getenv('AMADEUS_KEY')
AMADEUS_SECRET = os.getenv('AMADEUS_SECRET')
DB_URL = os.getenv('DATABASE_URL')

if not AMADEUS_KEY or not AMADEUS_SECRET:
    print("❌ Keys missing.")
    exit(1)

amadeus = Client(client_id=AMADEUS_KEY, client_secret=AMADEUS_SECRET)

def run_pipeline():
    if not DB_URL:
        print("❌ DB URL missing.")
        return

    with psycopg.connect(DB_URL, sslmode='require') as conn:
        with conn.cursor() as cursor:
            
            print("Fetching wishlist...")
            # UPDATED SELECT: fetching is_direct
            cursor.execute("SELECT origin_code, dest_code, flight_date, return_date, is_direct FROM tracked_routes")
            db_routes = cursor.fetchall()
            
            if not db_routes:
                print("No routes found.")
                return

            for r in db_routes:
                # UPDATED UNPACKING: 5 variables now
                origin, dest, date_obj, return_date_obj, is_direct_pref = r
                date_str = str(date_obj)
                
                # Check for duplicates (Idempotency)
                check_query = """
                    SELECT COUNT(*) FROM raw_flights 
                    WHERE origin_code = %s 
                    AND dest_code = %s 
                    AND flight_date = %s 
                    AND DATE(scraped_at) = CURRENT_DATE
                """
                cursor.execute(check_query, (origin, dest, date_str))
                if cursor.fetchone()[0] > 0:
                    print(f"⏩ Skipping {origin}->{dest} (Done today).")
                    continue 

                try:
                    # Logic Display
                    direct_msg = " (Direct Only ⚡)" if is_direct_pref else ""
                    if return_date_obj:
                        print(f"\n🔎 Checking {origin}->{dest}{direct_msg} | Dep: {date_str} | Ret: {return_date_obj}")
                    else:
                        print(f"\n🔎 Checking {origin}->{dest}{direct_msg} | Dep: {date_str}")
                    
                    # 3. PREPARE PARAMETERS
                    api_params = {
                        "originLocationCode": origin,
                        "destinationLocationCode": dest,
                        "departureDate": date_str,
                        "adults": 1,
                        "max": 5
                    }
                    if return_date_obj:
                        api_params["returnDate"] = str(return_date_obj)
                    
                    # --- NEW LOGIC: DIRECT FLIGHTS ---
                    if is_direct_pref:
                        api_params["nonStop"] = True
                    # ---------------------------------

                    # 4. CALL API
                    response = amadeus.shopping.flight_offers_search.get(**api_params)
                    
                    if not response.data:
                        print(f"   ⚠️  0 flights found.")
                    
                    # 5. SAVE
                    data_json = json.dumps(response.data)
                    query = """
                        INSERT INTO raw_flights (origin_code, dest_code, flight_date, raw_response)
                        VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(query, (origin, dest, date_str, data_json))
                    conn.commit()
                    print(f"   ✅ Saved.")

                except ResponseError as error:
                    print(f"   ❌ API Error: {error}")
                except Exception as e:
                    print(f"   ❌ Database Error: {e}")
                    conn.rollback() 

if __name__ == "__main__":
    run_pipeline()