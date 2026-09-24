"""Forecast tests that need neither a database nor the real model."""

import math
from datetime import datetime, timedelta, timezone

import pytest

import forecast
from conftest import FakeModel


def test_smoke_test_passes_with_a_working_model():
    assert forecast.smoke_test(FakeModel()) == 0


def test_rows_are_hour_aligned_and_ordered():
    origin = datetime(2026, 9, 24, 11, tzinfo=timezone.utc)
    rows = forecast.prediction_rows(origin, {"Solar": [(-3, 1, 2)] * 24}, "m", origin)
    assert rows[0]["prediction_timestamp"] == origin + timedelta(hours=1)
    assert rows[-1]["prediction_timestamp"] == origin + timedelta(hours=24)
    assert (rows[0]["predicted_low"], rows[0]["predicted_value"], rows[0]["predicted_high"]) == (0.0, 1.0, 2.0)


def test_empty_history_is_an_error():
    with pytest.raises(RuntimeError, match="no complete hours"):
        forecast.build_contexts([], datetime.now(timezone.utc))


def test_nan_context_reaches_the_model():
    origin = datetime(2026, 9, 24, 11, tzinfo=timezone.utc)
    rows = [(origin - timedelta(hours=h), 100, 30, 5, 40, 15) for h in range(80) if h != 3]
    _, contexts = forecast.build_contexts(rows, origin)
    assert math.isnan(contexts["Wind"][-4]) and contexts["Wind"][-1] == 30.0
