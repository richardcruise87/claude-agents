"""Unit tests for agents_lib.tracking."""
import json
import pytest
from agents_lib.tracking import (
    load_tracking_file,
    save_tracking_file,
    should_process_item,
    record_processed_item,
    create_output_filename,
)


class TestLoadTrackingFile:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = load_tracking_file(tmp_path / "nonexistent.json")
        assert result == {}

    def test_loads_existing_file(self, sample_tracking_file):
        result = load_tracking_file(sample_tracking_file)
        assert "bug_12345" in result

    def test_corrupt_json_raises(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ not valid json }")
        with pytest.raises(json.JSONDecodeError):
            load_tracking_file(bad_file)


class TestSaveTrackingFile:
    def test_creates_file(self, tmp_path):
        path = tmp_path / "tracking.json"
        save_tracking_file(path, {"key": "value"})
        assert path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "tracking.json"
        save_tracking_file(path, {})
        assert path.exists()

    def test_round_trip(self, tmp_path):
        data = {"item_1": {"sequence": 2, "last_updated": "2026-01-01"}}
        path = tmp_path / "t.json"
        save_tracking_file(path, data)
        loaded = load_tracking_file(path)
        assert loaded == data


class TestShouldProcessItem:
    def test_never_seen_returns_true_seq1(self):
        should, seq = should_process_item("123", "2026-01-01", {})
        assert should is True
        assert seq == 1

    def test_same_timestamp_returns_false(self):
        history = {"123": {"last_updated": "2026-01-01T10:00:00", "sequence": 1}}
        should, seq = should_process_item("123", "2026-01-01T10:00:00", history)
        assert should is False
        assert seq == 1

    def test_newer_timestamp_returns_true_with_incremented_seq(self):
        history = {"123": {"last_updated": "2026-01-01T10:00:00", "sequence": 1}}
        should, seq = should_process_item("123", "2026-01-02T10:00:00", history)
        assert should is True
        assert seq == 2

    def test_older_timestamp_returns_false(self):
        history = {"123": {"last_updated": "2026-01-15T10:00:00", "sequence": 3}}
        should, seq = should_process_item("123", "2026-01-01T10:00:00", history)
        assert should is False

    def test_id_prefix_applied(self):
        history = {"bug_999": {"last_updated": "2026-01-01", "sequence": 1}}
        # Without prefix: key "999" not in history → should process
        should, _ = should_process_item("999", "2026-01-01", history)
        assert should is True
        # With prefix: key "bug_999" found → same timestamp, should not process
        should, _ = should_process_item("999", "2026-01-01", history, id_prefix="bug_")
        assert should is False

    def test_sequence_increments_correctly(self):
        history = {"x": {"last_updated": "2026-01-01", "sequence": 5}}
        should, seq = should_process_item("x", "2026-06-01", history)
        assert should is True
        assert seq == 6


class TestCreateOutputFilename:
    def test_basic_format(self, tmp_path):
        path = create_output_filename(tmp_path, "123", "My Bug Title", 1, prefix="bug")
        name = path.name
        assert name.startswith("bug_123_")
        assert "_1.md" in name
        assert "my_bug_title" in name

    def test_no_prefix(self, tmp_path):
        path = create_output_filename(tmp_path, "123", "title", 1)
        assert path.name.startswith("123_")

    def test_long_title_truncated(self, tmp_path):
        long_title = "A" * 200
        path = create_output_filename(tmp_path, "1", long_title, 1, prefix="bug")
        # Slug portion should be <= 50 chars
        name_without_prefix = path.stem
        parts = name_without_prefix.split("_")
        # The slug portion (index 2) should be short
        slug_part = parts[2]
        assert len(slug_part) <= 50

    def test_uses_custom_extension(self, tmp_path):
        path = create_output_filename(tmp_path, "1", "title", 1, extension=".txt")
        assert path.suffix == ".txt"

    def test_returns_path_in_output_dir(self, tmp_path):
        path = create_output_filename(tmp_path, "1", "title", 1)
        assert path.parent == tmp_path


class TestRecordProcessedItem:
    def test_creates_new_entry(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, "42", "2026-03-01", 1)
        history = load_tracking_file(tf)
        assert "42" in history
        assert history["42"]["sequence"] == 1
        assert history["42"]["last_updated"] == "2026-03-01"

    def test_with_prefix(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, "99", "2026-01-01", 1, id_prefix="bug_")
        history = load_tracking_file(tf)
        assert "bug_99" in history

    def test_extra_data_stored(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, "1", "2026-01-01", 1, extra_data={"status": "DONE"})
        history = load_tracking_file(tf)
        assert history["1"]["status"] == "DONE"

    def test_updates_existing_entry(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, "1", "2026-01-01", 1)
        record_processed_item(tf, "1", "2026-06-01", 2)
        history = load_tracking_file(tf)
        assert history["1"]["sequence"] == 2
        assert history["1"]["last_updated"] == "2026-06-01"
