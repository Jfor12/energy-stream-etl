"""Forecast the next 24 hours of grid carbon intensity and generation mix
with Amazon's Chronos-Bolt time-series model, and store the forecasts in
grid_predictions so the forecast_accuracy view can score them later.
"""

import argparse
import logging
import math
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from etl_job import connect, ensure_schema, log_run, log_failure

logger = logging.getLogger("grid_forecast")

MODEL_ID = os.getenv("FORECAST_MODEL", "amazon/chronos-bolt-small")
HORIZON = 24  # hours ahead
CONTEXT_HOURS = 14 * 24  # history the model sees
MIN_POINTS = 72  # refuse to forecast from less than three days of data
MAX_STALENESS = timedelta(hours=3)  # the ETL has stalled if the latest hour is older
QUANTILES = (0.1, 0.5, 0.9)  # low, median, high: an 80% prediction interval

# Forecast name (as stored in grid_predictions.fuel_type) -> grid_telemetry column.
METRICS = {
    "Overall_Intensity": "overall_intensity",
    "Wind": "fuel_wind_perc",
    "Solar": "fuel_solar_perc",
    "Gas": "fuel_gas_perc",
    "Nuclear": "fuel_nuclear_perc",
}


def limits(metric: str) -> tuple:
    return (0.0, 1000.0) if metric == "Overall_Intensity" else (0.0, 100.0)


def load_history(conn, now: datetime) -> List[tuple]:
    """Complete hours (both half-hour readings) from the last CONTEXT_HOURS.
    Rows loaded before half_hours existed count as complete."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT timestamp, {", ".join(METRICS.values())}
            FROM grid_telemetry
            WHERE timestamp > %s AND timestamp <= %s
              AND EXTRACT(MINUTE FROM timestamp) = 0
              AND (half_hours IS NULL OR half_hours = 2)
            ORDER BY timestamp
            """,
            (now - timedelta(hours=CONTEXT_HOURS + 6), now),
        )
        return cur.fetchall()


def build_contexts(rows: List[tuple], now: datetime) -> tuple:
    """Turn rows into one regular hourly series per metric ending at the latest
    complete hour (the forecast origin). Missing hours become NaN, which the
    model treats as missing. Returns (origin, {metric: [values]})."""
    if not rows:
        raise RuntimeError("grid_telemetry has no complete hours to forecast from")
    by_hour = {row[0].astimezone(timezone.utc): row[1:] for row in rows}
    origin = max(by_hour)
    if now - origin > MAX_STALENESS:
        raise RuntimeError(f"The latest complete hour is {origin:%Y-%m-%d %H:%M} UTC; is the ETL running?")

    hours = [origin - timedelta(hours=CONTEXT_HOURS - 1 - i) for i in range(CONTEXT_HOURS)]
    contexts = {}
    for i, metric in enumerate(METRICS):
        series = [by_hour.get(hour, (None,) * len(METRICS))[i] for hour in hours]
        series = [math.nan if value is None else float(value) for value in series]
        known = sum(not math.isnan(value) for value in series)
        if known < MIN_POINTS:
            raise RuntimeError(f"Only {known} hours of {metric} history; need at least {MIN_POINTS}")
        contexts[metric] = series
    return origin, contexts


def load_pipeline(model_id: str):
    from chronos import BaseChronosPipeline
    logger.info(f"Loading {model_id}")
    return BaseChronosPipeline.from_pretrained(model_id, device_map="cpu")


def predict(pipeline, contexts: Dict[str, List[float]]) -> Dict[str, List[tuple]]:
    """Run the model on every metric at once. Returns {metric: [(low, median, high)] * HORIZON}."""
    try:
        import torch
        inputs = torch.tensor(list(contexts.values()), dtype=torch.float32)
    except ImportError:  # the tests use a stand-in model without torch
        inputs = list(contexts.values())
    quantiles, _mean = pipeline.predict_quantiles(inputs, prediction_length=HORIZON, quantile_levels=list(QUANTILES))
    quantiles = quantiles.tolist()  # [metric][hour][quantile]
    return {metric: [tuple(step) for step in quantiles[i]] for i, metric in enumerate(contexts)}


def prediction_rows(origin: datetime, forecasts: Dict[str, List[tuple]], model_id: str, created_at: datetime) -> List[dict]:
    rows = []
    for metric, steps in forecasts.items():
        low_limit, high_limit = limits(metric)
        clamp = lambda value: min(max(float(value), low_limit), high_limit)
        for h, (low, median, high) in enumerate(steps, start=1):
            low, median, high = sorted((clamp(low), clamp(median), clamp(high)))
            rows.append({
                "model": model_id,
                "fuel_type": metric,
                "forecast_origin": origin,
                "prediction_timestamp": origin + timedelta(hours=h),
                "predicted_value": round(median, 2),
                "predicted_low": round(low, 2),
                "predicted_high": round(high, 2),
                "created_at": created_at,
            })
    return rows


INSERT_SQL = """
    INSERT INTO grid_predictions
        (model, fuel_type, forecast_origin, prediction_timestamp, predicted_value, predicted_low, predicted_high, created_at)
    VALUES
        (%(model)s, %(fuel_type)s, %(forecast_origin)s, %(prediction_timestamp)s,
         %(predicted_value)s, %(predicted_low)s, %(predicted_high)s, %(created_at)s)
    ON CONFLICT (model, fuel_type, forecast_origin, prediction_timestamp) WHERE model IS NOT NULL DO NOTHING
"""


def store(conn, rows: List[dict]) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(INSERT_SQL, row)
            inserted += cur.rowcount
    conn.commit()
    return inserted


def already_forecast(conn, model_id: str, origin: datetime) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM grid_predictions WHERE model = %s AND forecast_origin = %s LIMIT 1", (model_id, origin))
        return cur.fetchone() is not None


def run(db_url: Optional[str], dry_run: bool = False, now: Optional[datetime] = None, pipeline=None, model_id: str = MODEL_ID) -> int:
    """Returns a process exit code: 0 on success, 1 on failure."""
    start = time.time()
    now = now or datetime.now(timezone.utc)
    if not db_url:
        logger.error("DATABASE_URL is not set")
        return 1
    try:
        with connect(db_url) as conn:
            ensure_schema(conn)
            origin, contexts = build_contexts(load_history(conn, now), now)
            if already_forecast(conn, model_id, origin):
                logger.info(f"Already forecast from {origin:%Y-%m-%d %H:%M} UTC with {model_id}; nothing to do")
                return 0
            forecasts = predict(pipeline or load_pipeline(model_id), contexts)
            rows = prediction_rows(origin, forecasts, model_id, now)
            for row in rows[::HORIZON]:  # the first hour of each metric
                logger.info(f"{row['fuel_type']} at {row['prediction_timestamp']:%H:%M}: {row['predicted_value']} "
                            f"({row['predicted_low']}-{row['predicted_high']})")
            if dry_run:
                logger.info(f"Dry run: {len(rows)} forecasts not stored")
                return 0
            inserted = store(conn, rows)
            log_run(conn, "forecast", "success", int((time.time() - start) * 1000), inserted)
        logger.info(f"✅ Stored {inserted} forecasts from {origin:%Y-%m-%d %H:%M} UTC")
        return 0
    except Exception:
        logger.exception("Forecast failed")
        if not dry_run:
            log_failure(db_url, "forecast", int((time.time() - start) * 1000), traceback.format_exc())
        return 1


def smoke_test(pipeline=None) -> int:
    """Check the model downloads and returns sensible shapes, without a database."""
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    daily = [math.sin(2 * math.pi * h / 24) for h in range(CONTEXT_HOURS)]
    contexts = {metric: [(limits(metric)[1] / 4) * (1.5 + value) for value in daily] for metric in METRICS}
    rows = prediction_rows(origin, predict(pipeline or load_pipeline(MODEL_ID), contexts), MODEL_ID, origin)
    ok = len(rows) == HORIZON * len(METRICS) and all(
        row["predicted_low"] <= row["predicted_value"] <= row["predicted_high"] and math.isfinite(row["predicted_value"])
        for row in rows
    )
    logger.info(f"Smoke test {'passed' if ok else 'FAILED'}: {len(rows)} forecasts, first: {rows[0] if rows else None}")
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="forecast but don't store anything")
    parser.add_argument("--smoke", action="store_true", help="run the model on synthetic data only (no database)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    if args.smoke:
        return smoke_test()
    return run(os.getenv("DATABASE_URL"), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
