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
            # Reverted Select
            cursor.execute("SELECT origin_code, dest_code, flight_date, return_date FROM tracked_routes")
            db_routes = cursor.fetchall()
            
            if not db_routes:
                print("No routes found.")
                return

            for r in db_routes:
                origin, dest, date_obj, return_date_obj = r
                date_str = str(date_obj)
                
                # Check for duplicates (Simple version again)
                check_query = """
                    SELECT COUNT(*) FROM raw_flights 
                    WHERE origin_code = %s 
                    AND dest_code = %s 
                    AND flight_date = %s 
                    AND DATE(ingested_at) = CURRENT_DATE
                """
                cursor.execute(check_query, (origin, dest, date_str))
                if cursor.fetchone()[0] > 0:
                    print(f"⏩ Skipping {origin}->{dest} (Already scraped today).")
                    continue 

                try:
                    if return_date_obj:
                        print(f"\n🔎 Checking {origin}->{dest} | Dep: {date_str} | Ret: {return_date_obj}")
                    else:
                        print(f"\n🔎 Checking {origin}->{dest} | Dep: {date_str}")
                    
                    # API Parameters (Standard)
                    api_params = {
                        "originLocationCode": origin,
                        "destinationLocationCode": dest,
                        "departureDate": date_str,
                        "adults": 1,
                        "max": 5
                    }
                    if return_date_obj:
                        api_params["returnDate"] = str(return_date_obj)
                    
                    # CALL API
                    response = amadeus.shopping.flight_offers_search.get(**api_params)
                    
                    if not response.data:
                        print(f"   ⚠️  0 flights found.")
                    
                    # SAVE (Simple Insert)
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
                    if error.response:
                         print(f"   ℹ️  Details: {error.response.body}")
                except Exception as e:
                    print(f"   ❌ Database Error: {e}")
                    conn.rollback() 

if __name__ == "__main__":
    run_pipeline()