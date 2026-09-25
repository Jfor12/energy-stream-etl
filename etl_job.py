"""Load GB grid carbon intensity and generation mix into Postgres.

Every run re-reads the last 24 hours from the Carbon Intensity API and
upserts one row per hour, so runs that GitHub delays or skips leave no gaps,
and forecast values are replaced by measured ones once they are published.
"""

import argparse
import functools
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import psycopg
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("grid_etl")

API_URL = "https://api.carbonintensity.org.uk"
FUELS = ("gas", "coal", "nuclear", "wind", "solar", "hydro", "biomass", "imports", "other")
HALF_HOUR = timedelta(minutes=30)
SQL_DIR = Path(__file__).resolve().parent / "sql"

# Retry configuration
MAX_RETRIES = 4
RETRY_DELAY = 2  # seconds, doubled after each attempt
MAX_RETRY_AFTER = 60  # never wait longer than this for a Retry-After header


class ValidationError(ValueError):
    pass


_unknown_fuels = set()


def retry_with_backoff(func):
    """Retry on connection errors, timeouts, 429 and 5xx responses with
    exponential backoff, honouring Retry-After. Other errors fail at once."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except requests.RequestException as e:
                response = getattr(e, "response", None)
                status = response.status_code if response is not None else None
                retryable = status is None or status == 429 or status >= 500
                if not retryable or attempt == MAX_RETRIES:
                    raise
                wait = RETRY_DELAY * 2 ** (attempt - 1)
                retry_after = response.headers.get("Retry-After") if response is not None else None
                if retry_after and retry_after.isdigit():
                    wait = min(int(retry_after), MAX_RETRY_AFTER)
                logger.warning(f"Attempt {attempt} failed ({e}); retrying in {wait}s")
                time.sleep(wait)
    return wrapper


@retry_with_backoff
def get_json(path: str) -> dict:
    response = requests.get(f"{API_URL}{path}", headers={"Accept": "application/json"}, timeout=20)
    response.raise_for_status()
    return response.json()


def api_time(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _parse_iso8601(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse API timestamps like "2024-05-21T19:00Z" into aware UTC datetimes."""
    if not ts_str:
        return None
    try:
        parsed = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _window(entry: dict) -> datetime:
    """Return the start of a half-hour window, checking it is one."""
    start, end = _parse_iso8601(entry.get("from")), _parse_iso8601(entry.get("to"))
    if start is None or end is None:
        raise ValidationError(f"unreadable window {entry.get('from')!r} -> {entry.get('to')!r}")
    if start.minute not in (0, 30) or start.second or end - start != HALF_HOUR:
        raise ValidationError(f"not a half-hour window: {entry.get('from')} -> {entry.get('to')}")
    return start


def _number(value, name: str, low: float, high: float) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} is {type(value).__name__}, expected a number")
    if not low <= value <= high:
        raise ValidationError(f"{name} {value} out of range ({low}-{high})")
    return float(value)


def validate_intensity_entry(entry: dict) -> dict:
    start = _window(entry)
    intensity = entry.get("intensity") or {}
    actual = _number(intensity.get("actual"), "actual intensity", 0, 1000)
    forecast = _number(intensity.get("forecast"), "forecast intensity", 0, 1000)
    if actual is None and forecast is None:
        raise ValidationError(f"no intensity value for {api_time(start)}")
    return {"start": start, "actual": actual, "forecast": forecast}


def validate_generation_entry(entry: dict) -> dict:
    start = _window(entry)
    # A fuel the API leaves out counts as 0% (coal, for example, since the last
    # coal plant closed). Fuels we don't store still count towards the total,
    # which must be about 100% or the reading is incomplete.
    mix = {fuel: 0.0 for fuel in FUELS}
    total = 0.0
    for item in entry.get("generationmix") or []:
        fuel = str(item.get("fuel", "")).lower()
        share = _number(item.get("perc"), f"{fuel or 'unnamed fuel'} share", 0, 100) or 0.0
        total += share
        if fuel in mix:
            mix[fuel] = share
        elif share and fuel not in _unknown_fuels:
            _unknown_fuels.add(fuel)
            logger.warning(f"Unrecognised fuel {fuel!r} ({share}%) is not stored")
    if not 98 <= total <= 102:  # shares are rounded to one decimal place
        raise ValidationError(f"generation mix for {api_time(start)} adds up to {total:.1f}%")
    return {"start": start, "mix": mix}


def parse_entries(entries, validate) -> tuple:
    """Validate API entries. Returns ({window start: entry}, [rejection reasons])."""
    if isinstance(entries, dict):  # the current-period endpoints return one object
        entries = [entries]
    valid, rejected = {}, []
    for entry in entries or []:
        try:
            parsed = validate(entry)
        except ValidationError as e:
            rejected.append(str(e))
            continue
        valid[parsed["start"]] = parsed
    return valid, rejected


def build_hourly_rows(intensity: Dict[datetime, dict], generation: Dict[datetime, dict]) -> List[dict]:
    """Average the half-hour windows that have both intensity and mix into one
    row per hour. Hours with neither window complete are left out."""
    hours: Dict[datetime, list] = {}
    for start in sorted(intensity.keys() & generation.keys()):
        hours.setdefault(start.replace(minute=0), []).append(start)

    rows = []
    for hour, starts in sorted(hours.items()):
        values = [intensity[s]["actual"] if intensity[s]["actual"] is not None else intensity[s]["forecast"] for s in starts]
        forecasts = [intensity[s]["forecast"] for s in starts if intensity[s]["forecast"] is not None]
        row = {
            "timestamp": hour,
            "overall_intensity": round(sum(values) / len(values)),
            "intensity_forecast": round(sum(forecasts) / len(forecasts)) if forecasts else None,
            "intensity_is_actual": all(intensity[s]["actual"] is not None for s in starts),
            "half_hours": len(starts),
        }
        for fuel in FUELS:
            row[f"fuel_{fuel}_perc"] = round(sum(generation[s]["mix"][fuel] for s in starts) / len(starts), 2)
        rows.append(row)
    return rows


def fetch_day(end: datetime) -> tuple:
    """Fetch and validate the 24 hours before `end`.
    Returns ({start: intensity}, {start: mix}, [rejection reasons])."""
    since = api_time(end)
    intensity, rejected_i = parse_entries(get_json(f"/intensity/{since}/pt24h").get("data"), validate_intensity_entry)
    generation, rejected_g = parse_entries(get_json(f"/generation/{since}/pt24h").get("data"), validate_generation_entry)
    if not intensity or not generation:
        raise RuntimeError(f"The API returned no usable data for the 24 hours before {since}")
    return intensity, generation, rejected_i + rejected_g


COLUMNS = ["timestamp", "overall_intensity", "intensity_forecast", "intensity_is_actual", "half_hours"] + [f"fuel_{f}_perc" for f in FUELS]
VALUE_COLUMNS = COLUMNS[1:]

UPSERT_BATCH = 500  # rows per statement, well under Postgres's parameter limit

UPSERT_SQL = f"""
    INSERT INTO grid_telemetry ({", ".join(COLUMNS)}, updated_at)
    VALUES {{values}}
    ON CONFLICT (timestamp) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in VALUE_COLUMNS)}, updated_at = NOW()
    WHERE ({", ".join(f"grid_telemetry.{c}" for c in VALUE_COLUMNS)})
        IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in VALUE_COLUMNS)})
      -- never replace a row with one built from fewer half hours
      AND EXCLUDED.half_hours >= COALESCE(grid_telemetry.half_hours, 0)
    RETURNING (xmax = 0) AS inserted
"""


def connect(db_url: str):
    options = {} if "sslmode=" in db_url else {"sslmode": "require"}
    # prepare_threshold=None: Supabase's transaction pooler does not support
    # prepared statements, which psycopg would otherwise use for repeated queries.
    return psycopg.connect(db_url, connect_timeout=15, prepare_threshold=None, **options)


def ensure_schema(conn):
    """Apply sql/schema.sql and sql/views.sql (both idempotent)."""
    try:
        with conn.cursor() as cur:
            for name in ("schema.sql", "views.sql"):
                cur.execute((SQL_DIR / name).read_text())
        conn.commit()
    except psycopg.errors.UniqueViolation as e:
        conn.rollback()
        raise RuntimeError(
            "grid_telemetry has several rows with the same timestamp, so the unique index "
            "cannot be created. Find them with: SELECT timestamp, COUNT(*) FROM grid_telemetry "
            "GROUP BY 1 HAVING COUNT(*) > 1; then delete the extra rows."
        ) from e


def upsert_rows(conn, rows: List[dict]) -> tuple:
    """Insert new hours and update changed ones, many rows per statement so a
    day is one round trip. Returns (inserted, updated)."""
    inserted = updated = 0
    placeholder = "(" + ", ".join(["%s"] * len(COLUMNS)) + ", NOW())"
    with conn.cursor() as cur:
        for i in range(0, len(rows), UPSERT_BATCH):
            batch = rows[i:i + UPSERT_BATCH]
            cur.execute(UPSERT_SQL.format(values=", ".join([placeholder] * len(batch))),
                        [row[c] for row in batch for c in COLUMNS])
            # Only inserted or changed rows come back; unchanged ones don't.
            for (was_inserted,) in cur.fetchall():
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1
    conn.commit()
    return inserted, updated


def log_run(conn, job: str, status: str, execution_time_ms: int, inserted=0, updated=0, rejected=0, error_message=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO etl_runs (job, status, rows_inserted, rows_updated, rows_rejected, execution_time_ms, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (job, status, inserted, updated, rejected, execution_time_ms, error_message),
        )
    conn.commit()


def run_pipeline(db_url: Optional[str], days: int = 1, dry_run: bool = False, now: Optional[datetime] = None) -> int:
    """Run the ETL. Returns a process exit code: 0 on success, 1 on failure."""
    start = time.time()
    elapsed_ms = lambda: int((time.time() - start) * 1000)
    now = now or datetime.now(timezone.utc)
    # End on the next whole hour, so each 24-hour request covers whole hours
    # and includes the current one.
    end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    if not db_url and not dry_run:
        logger.error("DATABASE_URL is not set")
        return 1

    logger.info(f"=== Grid ETL: {days} day(s) up to {api_time(end)}{' (dry run)' if dry_run else ''} ===")
    if not dry_run:
        try:
            with connect(db_url) as conn:
                ensure_schema(conn)
        except Exception:
            logger.exception("Preparing the database failed")
            log_failure(db_url, "etl", elapsed_ms(), traceback.format_exc())
            return 1

    # Each day is fetched and saved on its own, so a long backfill keeps what
    # it has loaded, and a day the API keeps failing on is skipped (and
    # reported) instead of losing the whole run. A rerun fills it in.
    rows_built = inserted = updated = 0
    rejected, skipped, latest = [], [], []
    for day in range(days):
        day_end = end - timedelta(days=day)
        try:
            intensity, generation, day_rejected = fetch_day(day_end)
        except Exception as e:
            logger.error(f"Skipped the 24 hours before {api_time(day_end)}: {e}")
            skipped.append(f"{api_time(day_end)}: {e}")
            continue
        rows = build_hourly_rows(intensity, generation)
        rows_built += len(rows)
        rejected += day_rejected
        latest = latest or rows[-3:]
        if not dry_run:
            try:
                with connect(db_url) as conn:
                    day_inserted, day_updated = upsert_rows(conn, rows)
            except Exception:
                logger.exception("Writing to the database failed")
                log_failure(db_url, "etl", elapsed_ms(), traceback.format_exc())
                return 1
            inserted += day_inserted
            updated += day_updated
        if days > 1:
            if (day + 1) % 30 == 0:
                logger.info(f"{day + 1}/{days} days loaded ({inserted} hours inserted, {updated} updated so far)")
            time.sleep(0.5)  # be gentle with the public API when backfilling

    for reason in rejected:
        logger.warning(f"Rejected: {reason}")
    logger.info(f"{rows_built} hourly rows built, {len(rejected)} half-hour readings rejected, "
                f"{len(skipped)} of {days} day(s) skipped")
    status = "failure" if len(skipped) == days else "partial" if skipped or rejected else "success"

    if dry_run:
        for row in latest:
            logger.info(f"Latest: {row}")
        return 1 if skipped else 0

    problems = [f"Skipped {reason}" for reason in skipped] + rejected
    try:
        with connect(db_url) as conn:
            log_run(conn, "etl", status, elapsed_ms(), inserted, updated, len(rejected),
                    "; ".join(problems)[:4000] or None)
    except Exception as e:
        logger.error(f"Could not record the run in etl_runs: {e}")
    logger.info(f"{'✅' if not skipped else '⚠️'} {inserted} hours inserted, {updated} updated, "
                f"{rows_built - inserted - updated} unchanged")
    # Skipped days turn the run red so they get noticed; what loaded is kept.
    return 1 if skipped else 0


def log_failure(db_url, job, execution_time_ms, error):
    """Record a failed run. If the database itself is the problem, the GitHub
    Actions log and the uploaded etl_pipeline.log still have the details."""
    try:
        with connect(db_url) as conn:
            log_run(conn, job, "failure", execution_time_ms, error_message=error[-4000:])
    except Exception as e:
        logger.error(f"Could not record the failed run in etl_runs: {e}")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("etl_pipeline.log"), logging.StreamHandler()],
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=1, help="how many days back to load (default 1; use more to backfill)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and validate only, without touching the database")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 400:
        parser.error("--days must be between 1 and 400")
    setup_logging()
    return run_pipeline(os.getenv("DATABASE_URL"), days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
