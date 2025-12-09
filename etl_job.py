import os
import psycopg
import requests
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('etl_pipeline.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv('DATABASE_URL')

CARBON_INTENSITY_URL = "https://api.carbonintensity.org.uk/intensity"
GENERATION_MIX_URL = "https://api.carbonintensity.org.uk/generation"

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

def retry_with_backoff(func):
    """Decorator for exponential backoff retry logic."""
    def wrapper(*args, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except requests.RequestException as e:
                if attempt == MAX_RETRIES - 1:
                    logger.error(f"Failed after {MAX_RETRIES} attempts: {e}")
                    raise
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
        return None
    return wrapper

def validate_intensity(value: Optional[int]) -> bool:
    """Validate carbon intensity value."""
    if value is None:
        logger.error("Validation failed: intensity is None")
        return False
    if not isinstance(value, (int, float)):
        logger.error(f"Validation failed: intensity type is {type(value)}, expected int/float")
        return False
    if value < 0 or value > 1000:
        logger.error(f"Validation failed: intensity {value} out of range (0-1000)")
        return False
    return True

def validate_fuel_percentage(name: str, value: float) -> bool:
    """Validate fuel percentage value."""
    if not isinstance(value, (int, float)):
        logger.error(f"Validation failed: {name} type is {type(value)}, expected float")
        return False
    if value < 0 or value > 100:
        logger.error(f"Validation failed: {name} {value}% out of range (0-100)")
        return False
    return True

def validate_timestamp(ts: Optional[datetime]) -> bool:
    """Validate timestamp is not None and not too old."""
    if ts is None:
        logger.error("Validation failed: timestamp is None")
        return False
    # Check if data is not older than 2 hours (API updates every 30 min)
    age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if age_hours > 2:
        logger.warning(f"Data freshness warning: timestamp is {age_hours:.1f} hours old")
    return True

def _parse_iso8601(ts_str):
    """Parse ISO8601 timestamps returned by the National Grid API."""
    if not ts_str:
        return None
    try:
        # API returns like "2024-05-21T19:00Z"; replace Z for fromisoformat
        ts_clean = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_clean)
    except Exception:
        return None

@retry_with_backoff
def fetch_intensity():
    logger.info(f"Fetching carbon intensity from {CARBON_INTENSITY_URL}")
    resp = requests.get(CARBON_INTENSITY_URL, timeout=10)
    resp.raise_for_status()
    payload = resp.json().get("data")
    if not payload:
        raise ValueError("No intensity data returned")
    record = payload[0]
    intensity_obj = record.get("intensity", {})
    intensity_value = intensity_obj.get("actual") or intensity_obj.get("forecast")
    from_time = _parse_iso8601(record.get("from")) or datetime.now(timezone.utc)
    to_time = _parse_iso8601(record.get("to"))
    logger.info(f"Fetched intensity: {intensity_value} gCO2/kWh at {from_time}")
    return intensity_value, from_time, to_time

@retry_with_backoff
def fetch_generation_mix():
    logger.info(f"Fetching generation mix from {GENERATION_MIX_URL}")
    resp = requests.get(GENERATION_MIX_URL, timeout=10)
    resp.raise_for_status()
    payload = resp.json().get("data")
    if not payload:
        raise ValueError("No generation data returned")
    # Endpoint sometimes returns a list; other times a dict with generationmix
    record = payload[0] if isinstance(payload, list) else payload
    mix = record.get("generationmix", [])

    def fuel_perc(fuel_name):
        for entry in mix:
            if entry.get("fuel", "").lower() == fuel_name:
                return float(entry.get("perc", 0))
        return 0.0

    mix_data = {
        "gas": fuel_perc("gas"),
        "nuclear": fuel_perc("nuclear"),
        "wind": fuel_perc("wind"),
        "solar": fuel_perc("solar"),
    }
    logger.info(f"Fetched generation mix: Wind={mix_data['wind']:.1f}%, Solar={mix_data['solar']:.1f}%")
    return mix_data

def ensure_table(conn):
    """Create target tables if they do not exist."""
    create_telemetry_sql = """
    CREATE TABLE IF NOT EXISTS grid_telemetry (
        id BIGSERIAL PRIMARY KEY,
        timestamp TIMESTAMPTZ DEFAULT NOW(),
        overall_intensity INT,
        fuel_gas_perc DOUBLE PRECISION,
        fuel_nuclear_perc DOUBLE PRECISION,
        fuel_wind_perc DOUBLE PRECISION,
        fuel_solar_perc DOUBLE PRECISION
    );
    """
    create_etl_runs_sql = """
    CREATE TABLE IF NOT EXISTS etl_runs (
        id BIGSERIAL PRIMARY KEY,
        run_timestamp TIMESTAMPTZ DEFAULT NOW(),
        status VARCHAR(20),
        rows_inserted INT,
        execution_time_ms INT,
        error_message TEXT
    );
    """
    with conn.cursor() as cur:
        cur.execute(create_telemetry_sql)
        cur.execute(create_etl_runs_sql)
        conn.commit()
    logger.info("Database tables verified/created")

def log_etl_run(conn, status: str, rows_inserted: int, execution_time_ms: int, error_message: Optional[str] = None):
    """Log ETL run metadata to etl_runs table."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO etl_runs (status, rows_inserted, execution_time_ms, error_message)
                VALUES (%s, %s, %s, %s)
                """,
                (status, rows_inserted, execution_time_ms, error_message)
            )
            conn.commit()
            logger.info(f"ETL run logged: {status}, {rows_inserted} rows, {execution_time_ms}ms")
    except Exception as e:
        logger.error(f"Failed to log ETL run metadata: {e}")

def run_pipeline():
    start_time = time.time()
    rows_inserted = 0
    status = "failure"
    error_message = None
    
    if not DB_URL:
        error_message = "DATABASE_URL missing"
        logger.error(f"❌ {error_message}")
        return

    logger.info("=== Starting CarbonStream ETL Pipeline ===")
    
    try:
        # Fetch data with retry logic
        intensity_value, from_time, to_time = fetch_intensity()
        mix = fetch_generation_mix()
        
        # Data quality validation
        logger.info("Running data quality checks...")
        validations = [
            validate_intensity(intensity_value),
            validate_timestamp(from_time),
            validate_fuel_percentage("gas", mix.get("gas", 0)),
            validate_fuel_percentage("nuclear", mix.get("nuclear", 0)),
            validate_fuel_percentage("wind", mix.get("wind", 0)),
            validate_fuel_percentage("solar", mix.get("solar", 0)),
        ]
        
        if not all(validations):
            error_message = "Data quality validation failed"
            logger.error(f"❌ {error_message}")
            status = "partial"
        else:
            logger.info("✅ All data quality checks passed")
        
        # Database insertion
        logger.info("Writing telemetry row to database...")
        with psycopg.connect(DB_URL, sslmode='require') as conn:
            ensure_table(conn)
            try:
                with conn.cursor() as cursor:
                    # Check if timestamp already exists to prevent duplicates
                    check_sql = """
                        SELECT COUNT(*) FROM grid_telemetry
                        WHERE timestamp = %s
                    """
                    cursor.execute(check_sql, (from_time,))
                    exists = cursor.fetchone()[0] > 0
                    
                    if exists:
                        logger.info(f"⏭️  Skipping duplicate - data already exists for timestamp: {from_time}")
                        rows_inserted = 0
                        status = "skipped"
                    else:
                        insert_sql = """
                            INSERT INTO grid_telemetry (
                                timestamp,
                                overall_intensity,
                                fuel_gas_perc,
                                fuel_nuclear_perc,
                                fuel_wind_perc,
                                fuel_solar_perc
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                        """
                        cursor.execute(
                            insert_sql,
                            (
                                from_time,
                                intensity_value,
                                mix.get("gas"),
                                mix.get("nuclear"),
                                mix.get("wind"),
                                mix.get("solar"),
                            ),
                        )
                        conn.commit()
                        rows_inserted = 1
                        status = "success"
                        logger.info(f"✅ Stored intensity={intensity_value}, wind={mix.get('wind')}% | window: {from_time} -> {to_time}")
                
                # Log ETL run metadata
                execution_time_ms = int((time.time() - start_time) * 1000)
                log_etl_run(conn, status, rows_inserted, execution_time_ms)
                
            except Exception as e:
                conn.rollback()
                error_message = f"Database write failed: {e}"
                logger.error(f"❌ {error_message}")
                execution_time_ms = int((time.time() - start_time) * 1000)
                log_etl_run(conn, status, rows_inserted, execution_time_ms, error_message)
                
    except Exception as e:
        error_message = f"Pipeline failed: {e}"
        logger.error(f"❌ {error_message}", exc_info=True)
        # Try to log failure even if DB connection fails
        try:
            with psycopg.connect(DB_URL, sslmode='require') as conn:
                ensure_table(conn)
                execution_time_ms = int((time.time() - start_time) * 1000)
                log_etl_run(conn, status, rows_inserted, execution_time_ms, error_message)
        except:
            logger.error("Could not log ETL run metadata")
    
    logger.info("=== Pipeline execution complete ===")

if __name__ == "__main__":
    logger.info("Starting ETL job")
    run_pipeline()
    logger.info("ETL job finished")