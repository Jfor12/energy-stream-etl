import os
import json
import psycopg
from amadeus import Client, ResponseError
# REMOVED: from dotenv import load_dotenv  <-- This was causing the crash

# 1. Load the secrets (Safe method)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 2. Initialize Client
amadeus = Client(
    client_id=os.getenv('AMADEUS_KEY'),
    client_secret=os.getenv('AMADEUS_SECRET')
)

DB_URL = os.getenv('DATABASE_URL')

def run_pipeline():
    # Force SSL to fix the "Duplicate SASL" error
    with psycopg.connect(DB_URL, sslmode='require') as conn:
        with conn.cursor() as cursor:
            
            # 1. FETCH ROUTES FROM DATABASE
            print("Fetching wishlist from database...")
            cursor.execute("SELECT origin_code, dest_code, flight_date, return_date FROM tracked_routes")
            db_routes = cursor.fetchall()
            
            if not db_routes:
                print("No routes found in database. Add some using your Streamlit App!")
                return

            # 2. PROCESS EACH ROUTE
            for r in db_routes:
                origin, dest, date_obj, return_date_obj = r
                date_str = str(date_obj)
                
                try:
                    print(f"Checking {origin} -> {dest} on {date_str}...")
                    
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

                    # 4. CALL API
                    response = amadeus.shopping.flight_offers_search.get(**api_params)
                    
                    # 5. SAVE RAW DATA
                    data_json = json.dumps(response.data)
                    
                    query = """
                        INSERT INTO raw_flights (origin_code, dest_code, flight_date, raw_response)
                        VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(query, (origin, dest, date_str, data_json))
                    
                    # IMPORTANT: You must commit the data!
                    conn.commit()
                    
                    print(f"Success! Saved data for {origin}->{dest}.")

                except ResponseError as error:
                    print(f"API Error for {origin}->{dest}: {error}")
                except Exception as e:
                    print(f"Database Error: {e}")
                    # Optional: Rollback if one insert fails so it doesn't break the connection
                    conn.rollback() 

if __name__ == "__main__":
    run_pipeline()