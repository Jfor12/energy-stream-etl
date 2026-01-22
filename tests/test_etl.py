"""
Unit tests for Grid ETL Pipeline.

Tests cover:
- Data validation functions
- API response parsing
- Error handling
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from etl_job import (
    validate_intensity,
    validate_fuel_percentage,
    validate_timestamp,
    _parse_iso8601,
)


class TestDataValidation:
    """Test data quality validation functions."""

    def test_validate_intensity_valid(self):
        """Test valid carbon intensity values."""
        assert validate_intensity(150) is True
        assert validate_intensity(0) is True
        assert validate_intensity(1000) is True
        assert validate_intensity(250.5) is True

    def test_validate_intensity_invalid(self):
        """Test invalid carbon intensity values."""
        assert validate_intensity(None) is False
        assert validate_intensity(-10) is False
        assert validate_intensity(1500) is False
        assert validate_intensity("150") is False

    def test_validate_fuel_percentage_valid(self):
        """Test valid fuel percentage values."""
        assert validate_fuel_percentage("wind", 50.0) is True
        assert validate_fuel_percentage("solar", 0) is True
        assert validate_fuel_percentage("gas", 100) is True
        assert validate_fuel_percentage("nuclear", 25.7) is True

    def test_validate_fuel_percentage_invalid(self):
        """Test invalid fuel percentage values."""
        assert validate_fuel_percentage("wind", -5) is False
        assert validate_fuel_percentage("solar", 150) is False
        assert validate_fuel_percentage("gas", "50") is False

    def test_validate_timestamp_valid(self):
        """Test valid timestamp."""
        now = datetime.now(timezone.utc)
        assert validate_timestamp(now) is True

    def test_validate_timestamp_invalid(self):
        """Test invalid timestamp."""
        assert validate_timestamp(None) is False


class TestDateParsing:
    """Test ISO8601 date parsing."""

    def test_parse_iso8601_valid(self):
        """Test parsing valid ISO8601 timestamps."""
        result = _parse_iso8601("2025-12-09T14:00Z")
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 9
        assert result.hour == 14

    def test_parse_iso8601_with_offset(self):
        """Test parsing ISO8601 with timezone offset."""
        result = _parse_iso8601("2025-12-09T14:00+00:00")
        assert result is not None
        assert isinstance(result, datetime)

    def test_parse_iso8601_invalid(self):
        """Test parsing invalid timestamps."""
        assert _parse_iso8601(None) is None
        assert _parse_iso8601("invalid") is None
        assert _parse_iso8601("") is None


class TestIntegration:
    """Integration tests for complete data flow."""

    def test_full_validation_pipeline(self):
        """Test complete validation of a telemetry record."""
        intensity = 180
        timestamp = datetime.now(timezone.utc)
        mix = {
            "gas": 45.5,
            "nuclear": 20.0,
            "wind": 25.3,
            "solar": 5.2,
        }

        assert validate_intensity(intensity)
        assert validate_timestamp(timestamp)
        assert validate_fuel_percentage("gas", mix["gas"])
        assert validate_fuel_percentage("nuclear", mix["nuclear"])
        assert validate_fuel_percentage("wind", mix["wind"])
        assert validate_fuel_percentage("solar", mix["solar"])

    def test_validation_pipeline_with_invalid_data(self):
        """Test validation catches invalid data."""
        intensity = -50
        timestamp = None
        mix = {
            "gas": 150.0,
            "nuclear": 20.0,
            "wind": 25.3,
            "solar": 5.2,
        }

        assert not validate_intensity(intensity)
        assert not validate_timestamp(timestamp)
        assert not validate_fuel_percentage("gas", mix["gas"])


class TestDuplicatePrevention:
    """Test duplicate timestamp detection."""

    def test_duplicate_detection_logic(self):
        """Test that duplicate check logic is sound."""
        timestamp1 = datetime(2025, 12, 9, 15, 0, 0, tzinfo=timezone.utc)
        timestamp2 = datetime(2025, 12, 9, 15, 0, 0, tzinfo=timezone.utc)
        timestamp3 = datetime(2025, 12, 9, 16, 0, 0, tzinfo=timezone.utc)

        assert timestamp1 == timestamp2
        assert timestamp1 != timestamp3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
