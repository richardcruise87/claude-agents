"""Unit tests for backport-agent/backport_tracker.py."""
from backport_tracker import (
    load_backport_tracking,
    record_backport,
    is_already_processed,
    get_backport_record,
    list_backport_records,
)


class TestIsAlreadyProcessed:
    def test_new_change_not_processed(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        assert is_already_processed(tracking, "123456", "stable/2024.2") is False

    def test_processed_change_detected(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "123456", "stable/2024.2", "BACKPORTED")
        assert is_already_processed(tracking, "123456", "stable/2024.2") is True

    def test_different_branch_not_processed(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "123456", "stable/2024.2", "BACKPORTED")
        assert is_already_processed(tracking, "123456", "stable/2024.1") is False

    def test_different_change_not_processed(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "123456", "stable/2024.2", "BACKPORTED")
        assert is_already_processed(tracking, "999999", "stable/2024.2") is False


class TestRecordBackport:
    def test_creates_entry(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "123456", "stable/2024.2", "BACKPORTED",
                        backport_change_url="https://review.opendev.org/c/+/987654")
        data = load_backport_tracking(tracking)
        assert "123456:stable/2024.2" in data
        entry = data["123456:stable/2024.2"]
        assert entry["status"] == "BACKPORTED"
        assert "backport_change_url" in entry

    def test_conflict_entry(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "123456", "stable/2024.1", "CONFLICT")
        entry = get_backport_record(tracking, "123456", "stable/2024.1")
        assert entry is not None
        assert entry["status"] == "CONFLICT"
        assert "backport_change_url" not in entry

    def test_all_status_values(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        for status in ("BACKPORTED", "CONFLICT", "SKIPPED", "PUSH_FAILED"):
            record_backport(tracking, "111111", f"stable/{status.lower()}", status)
        data = load_backport_tracking(tracking)
        assert len(data) == 4


class TestGetBackportRecord:
    def test_returns_none_for_missing(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        assert get_backport_record(tracking, "999", "stable/2024.2") is None

    def test_returns_record(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "999", "stable/2024.2", "BACKPORTED",
                        commit_sha="abc123")
        record = get_backport_record(tracking, "999", "stable/2024.2")
        assert record is not None
        assert record["upstream_commit_sha"] == "abc123"


class TestListBackportRecords:
    def test_lists_all(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "111", "stable/2024.2", "BACKPORTED")
        record_backport(tracking, "222", "stable/2024.2", "CONFLICT")
        records = list_backport_records(tracking)
        assert len(records) == 2

    def test_filters_by_change_id(self, tmp_path):
        tracking = tmp_path / "tracking.json"
        record_backport(tracking, "111", "stable/2024.2", "BACKPORTED")
        record_backport(tracking, "111", "stable/2024.1", "CONFLICT")
        record_backport(tracking, "222", "stable/2024.2", "BACKPORTED")
        records = list_backport_records(tracking, change_id="111")
        assert len(records) == 2
        assert all(r["change_id"] == "111" for r in records)
