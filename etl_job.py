import os
import json
import psycopg2
from amadeus import Client, ResponseError

# 1. Setup Connections (using Environment Variables for security)
amadeus = Client(
    client_id=os.getenv('AMADEUS_KEY'),
    client_secret=os.getenv('AMADEUS_SECRET')
)

DB_URL = os.getenv('DATABASE_URL')

# 2. Define what we want to track
routes = [
    {"origin": "LHR", "dest": "JFK", "date": "2024-12-25"},
    {"origin": "SFO", "dest": "TYO", "date": "2024-12-20"}
]

def run_pipeline():
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    
    for route in routes:
        try:
            # 3. EXTRACT: Call API
            response = amadeus.shopping.flight_offers_search.get(
                originLocationCode=route['origin'],
                destinationLocationCode=route['dest'],
                departureDate=route['date'],
                adults=1,
                max=5
            )
            
            # 4. LOAD: Dump the RAW JSON into Postgres
            # We don't clean it yet. That's the Data Engineer way.
            data_json = json.dumps(response.data)
            
            query = """
                INSERT INTO raw_flights (origin_code, dest_code, flight_date, raw_response)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(query, (route['origin'], route['dest'], route['date'], data_json))
            print(f"Loaded data for {route['origin']} -> {route['dest']}")

        except ResponseError as error:
            print(f"Error: {error}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run_pipeline()
