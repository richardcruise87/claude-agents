"""Unit tests for ci-failure-agent/failure_tracker.py."""
import json
from failure_tracker import (
    get_failure_key,
    has_been_analyzed,
    record_analyzed_failure,
)


class TestGetFailureKey:
    def test_format(self):
        key = get_failure_key("982567", "3", "check")
        assert key == "982567~ps3~check"

    def test_different_pipelines(self):
        assert get_failure_key("1", "1", "gate") == "1~ps1~gate"
        assert get_failure_key("1", "1", "check") == "1~ps1~check"

    def test_string_conversion(self):
        key = get_failure_key(982567, 3, "check")
        assert "982567" in key


class TestHasBeenAnalyzed:
    def test_not_in_history(self, tmp_path):
        tf = tmp_path / "track.json"
        already, seq = has_been_analyzed(tf, "123", "1", "check", "2026-01-01T00:00:00")
        assert already is False
        assert seq == 1

    def test_same_timestamp_already_analyzed(self, tmp_path):
        tf = tmp_path / "track.json"
        record_analyzed_failure(tf, "123", "1", "check", "2026-01-01T00:00:00", 1)
        already, seq = has_been_analyzed(tf, "123", "1", "check", "2026-01-01T00:00:00")
        assert already is True

    def test_new_failure_triggers_reanalysis(self, tmp_path):
        tf = tmp_path / "track.json"
        record_analyzed_failure(tf, "123", "1", "check", "2026-01-01T00:00:00", 1)
        already, seq = has_been_analyzed(tf, "123", "1", "check", "2026-06-01T00:00:00")
        assert already is False
        assert seq == 2

    def test_different_pipeline_independent(self, tmp_path):
        tf = tmp_path / "track.json"
        record_analyzed_failure(tf, "123", "1", "check", "2026-01-01", 1)
        already, seq = has_been_analyzed(tf, "123", "1", "gate", "2026-01-01")
        assert already is False


class TestRecordAnalyzedFailure:
    def test_creates_entry(self, tmp_path):
        tf = tmp_path / "track.json"
        record_analyzed_failure(tf, "456", "2", "check", "2026-03-01T00:00:00", 1)
        data = json.loads(tf.read_text())
        key = get_failure_key("456", "2", "check")
        assert key in data
        assert data[key]["sequence"] == 1

    def test_extra_data_stored(self, tmp_path):
        tf = tmp_path / "track.json"
        record_analyzed_failure(
            tf, "1", "1", "check", "2026-01-01", 1,
            extra_data={"report_file": "/tmp/report.md"}
        )
        data = json.loads(tf.read_text())
        key = get_failure_key("1", "1", "check")
        assert data[key]["report_file"] == "/tmp/report.md"

    def test_sequence_increments(self, tmp_path):
        tf = tmp_path / "track.json"
        record_analyzed_failure(tf, "1", "1", "check", "2026-01-01", 1)
        record_analyzed_failure(tf, "1", "1", "check", "2026-06-01", 2)
        data = json.loads(tf.read_text())
        key = get_failure_key("1", "1", "check")
        assert data[key]["sequence"] == 2
        assert data[key]["last_updated"] == "2026-06-01"
