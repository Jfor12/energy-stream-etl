"""Unit tests for the ETL: parsing, validation, hourly averaging and retries.
None of these need a database or the network."""

from datetime import datetime, timedelta, timezone

import pytest
import requests

import etl_job
from conftest import MIX, fake_api, generation_entry, intensity_entry

T = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


class TestParsing:
    def test_parse_iso8601(self):
        assert etl_job._parse_iso8601("2025-12-09T14:00Z") == datetime(2025, 12, 9, 14, tzinfo=timezone.utc)
        assert etl_job._parse_iso8601("2025-12-09T15:00+01:00") == datetime(2025, 12, 9, 14, tzinfo=timezone.utc)
        for bad in (None, "", "invalid", "2025-12-09T14:00"):  # the last has no timezone
            assert etl_job._parse_iso8601(bad) is None

    def test_intensity_entry(self):
        parsed = etl_job.validate_intensity_entry(intensity_entry(T, actual=None, forecast=140))
        assert parsed == {"start": T, "actual": None, "forecast": 140.0}

    def test_generation_accepts_a_single_object(self):
        # The current-period endpoint returns data as an object, not a list.
        valid, rejected = etl_job.parse_entries(generation_entry(T), etl_job.validate_generation_entry)
        assert list(valid) == [T] and rejected == []
        assert valid[T]["mix"]["wind"] == 35.0

    def test_missing_fuel_counts_as_zero(self):
        mix = {k: v for k, v in MIX.items() if k != "coal"}
        assert etl_job.validate_generation_entry(generation_entry(T, mix))["mix"]["coal"] == 0.0

    def test_unknown_fuel_counts_towards_the_total(self):
        mix = {**MIX, "gas": 25.0, "storage": 5.0}
        assert etl_job.validate_generation_entry(generation_entry(T, mix))["mix"]["gas"] == 25.0


class TestValidation:
    @pytest.mark.parametrize("entry, reason", [
        (intensity_entry(T, actual=None, forecast=None), "no intensity value"),
        (intensity_entry(T, actual=-5), "out of range"),
        (intensity_entry(T, actual=1500), "out of range"),
        (intensity_entry(T, actual="150"), "expected a number"),
        ({**intensity_entry(T), "from": "2026-09-24T10:10Z", "to": "2026-09-24T10:40Z"}, "not a half-hour window"),
        ({**intensity_entry(T), "to": "2026-09-24T11:00Z"}, "not a half-hour window"),
        ({**intensity_entry(T), "from": None}, "unreadable window"),
    ])
    def test_bad_intensity_is_rejected(self, entry, reason):
        valid, rejected = etl_job.parse_entries([entry], etl_job.validate_intensity_entry)
        assert valid == {} and reason in rejected[0]

    @pytest.mark.parametrize("mix, reason", [
        ({"gas": 45.0, "wind": 30.0}, "adds up to 75.0%"),
        ({**MIX, "gas": 150.0}, "out of range"),
        ({**MIX, "gas": "30"}, "expected a number"),
    ])
    def test_bad_mix_is_rejected(self, mix, reason):
        valid, rejected = etl_job.parse_entries([generation_entry(T, mix)], etl_job.validate_generation_entry)
        assert valid == {} and reason in rejected[0]

    def test_null_share_counts_as_zero(self):
        mix = {**MIX, "wind": None, "gas": 65.0}
        assert etl_job.validate_generation_entry(generation_entry(T, mix))["mix"]["wind"] == 0.0


class TestHourlyRows:
    def build(self, intensities, mixes):
        intensity, _ = etl_job.parse_entries(intensities, etl_job.validate_intensity_entry)
        generation, _ = etl_job.parse_entries(mixes, etl_job.validate_generation_entry)
        return etl_job.build_hourly_rows(intensity, generation)

    def test_both_half_hours_are_averaged(self):
        later = T + timedelta(minutes=30)
        rows = self.build(
            [intensity_entry(T, actual=100, forecast=110), intensity_entry(later, actual=201, forecast=190)],
            [generation_entry(T), generation_entry(later, {**MIX, "wind": 45.0, "gas": 20.0})],
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["timestamp"] == T
        assert row["overall_intensity"] == 150  # (100 + 201) / 2 rounded
        assert row["intensity_forecast"] == 150
        assert row["intensity_is_actual"] is True
        assert row["half_hours"] == 2
        assert row["fuel_wind_perc"] == 40.0 and row["fuel_gas_perc"] == 25.0

    def test_forecast_is_used_until_the_actual_arrives(self):
        later = T + timedelta(minutes=30)
        rows = self.build(
            [intensity_entry(T, actual=100), intensity_entry(later, actual=None, forecast=120)],
            [generation_entry(T), generation_entry(later)],
        )
        assert rows[0]["overall_intensity"] == 110
        assert rows[0]["intensity_is_actual"] is False

    def test_half_hour_without_a_mix_is_left_out(self):
        later = T + timedelta(minutes=30)
        rows = self.build([intensity_entry(T), intensity_entry(later, actual=300)], [generation_entry(T)])
        assert rows[0]["half_hours"] == 1 and rows[0]["overall_intensity"] == 150

    def test_the_second_half_hour_is_not_filed_under_the_wrong_hour(self):
        rows = self.build([intensity_entry(T + timedelta(minutes=90))], [generation_entry(T + timedelta(minutes=90))])
        assert rows[0]["timestamp"] == T + timedelta(hours=1)

    def test_fetch_day_covers_24_hours(self, monkeypatch):
        monkeypatch.setattr(etl_job, "get_json", fake_api(T))
        intensity, generation, rejected = etl_job.fetch_day(T)
        rows = etl_job.build_hourly_rows(intensity, generation)
        assert len(rows) == 24 and rejected == []
        assert all(row["half_hours"] == 2 for row in rows)


def http_error(status, retry_after=None):
    response = requests.Response()
    response.status_code = status
    if retry_after:
        response.headers["Retry-After"] = retry_after
    return requests.HTTPError(f"{status} error", response=response)


class TestRetries:
    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        self.sleeps = []
        monkeypatch.setattr(etl_job.time, "sleep", self.sleeps.append)

    def flaky(self, errors):
        calls = []

        @etl_job.retry_with_backoff
        def call():
            calls.append(1)
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            return "ok"
        return call, calls

    def test_retries_server_errors_with_backoff(self):
        call, calls = self.flaky([http_error(503), requests.ConnectionError("reset")])
        assert call() == "ok" and len(calls) == 3
        assert self.sleeps == [2, 4]

    def test_honours_retry_after(self):
        call, _ = self.flaky([http_error(429, retry_after="7")])
        assert call() == "ok" and self.sleeps == [7]

    def test_caps_retry_after(self):
        call, _ = self.flaky([http_error(429, retry_after="3600")])
        call()
        assert self.sleeps == [etl_job.MAX_RETRY_AFTER]

    def test_client_errors_fail_at_once(self):
        call, calls = self.flaky([http_error(400)])
        with pytest.raises(requests.HTTPError):
            call()
        assert len(calls) == 1 and self.sleeps == []

    def test_gives_up_after_max_retries(self):
        call, calls = self.flaky([requests.Timeout("slow")] * 10)
        with pytest.raises(requests.Timeout):
            call()
        assert len(calls) == etl_job.MAX_RETRIES


class TestExitCodes:
    def test_missing_database_url_fails(self):
        assert etl_job.run_pipeline(None) == 1

    def test_api_failure_fails_the_run(self, monkeypatch):
        def broken(path):
            raise requests.HTTPError("404", response=requests.Response())
        monkeypatch.setattr(etl_job, "get_json", broken)
        assert etl_job.run_pipeline(None, dry_run=True) == 1

    def test_dry_run_needs_no_database(self, monkeypatch, now):
        monkeypatch.setattr(etl_job, "get_json", fake_api(now.replace(minute=0)))
        assert etl_job.run_pipeline(None, dry_run=True, now=now) == 0

    def test_days_is_bounded(self):
        with pytest.raises(SystemExit):
            etl_job.main(["--days", "0"])
