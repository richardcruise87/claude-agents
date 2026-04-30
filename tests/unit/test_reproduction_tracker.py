"""Unit tests for bug-reproduction-agent/reproduction_tracker.py."""
import json
from reproduction_tracker import (
    should_reproduce_bug,
    record_reproduction,
    load_reproduction_history,
    create_reproduction_filename,
    find_previous_reproductions,
)


class TestShouldReproduceBug:
    def test_new_bug_should_reproduce(self):
        should, seq = should_reproduce_bug("12345", "2026-03-30T10:00:00", {})
        assert should is True
        assert seq == 1

    def test_same_triage_timestamp_should_not_reproduce(self, tmp_path):
        tf = tmp_path / "track.json"
        record_reproduction(tf, "12345", "2026-03-30T10:00:00", 1, "REPRODUCED", 1)
        history = load_reproduction_history(tf)
        should, seq = should_reproduce_bug("12345", "2026-03-30T10:00:00", history)
        assert should is False
        assert seq == 1

    def test_new_triage_triggers_re_reproduction(self, tmp_path):
        tf = tmp_path / "track.json"
        record_reproduction(tf, "12345", "2026-03-30T10:00:00", 1, "NOT_REPRODUCED", 3)
        history = load_reproduction_history(tf)
        should, seq = should_reproduce_bug("12345", "2026-04-01T00:00:00", history)
        assert should is True
        assert seq == 2

    def test_different_bugs_independent(self, tmp_path):
        tf = tmp_path / "track.json"
        record_reproduction(tf, "111", "2026-01-01", 1, "REPRODUCED", 1)
        history = load_reproduction_history(tf)
        should, seq = should_reproduce_bug("222", "2026-01-01", history)
        assert should is True
        assert seq == 1


class TestRecordReproduction:
    def test_creates_entry(self, tmp_path):
        tf = tmp_path / "track.json"
        record_reproduction(tf, "42", "2026-03-01", 1, "REPRODUCED", 2, "/path/script.sh")
        data = json.loads(tf.read_text())
        assert "bug_42" in data
        entry = data["bug_42"]
        assert entry["reproduction_status"] == "REPRODUCED"
        assert entry["attempts"] == 2
        assert entry["final_script_path"] == "/path/script.sh"

    def test_no_script_path_when_none(self, tmp_path):
        tf = tmp_path / "track.json"
        record_reproduction(tf, "1", "2026-01-01", 1, "NOT_REPRODUCED", 3)
        data = json.loads(tf.read_text())
        assert "final_script_path" not in data["bug_1"]

    def test_status_values(self, tmp_path):
        tf = tmp_path / "track.json"
        for status in ["REPRODUCED", "NOT_REPRODUCED", "ENVIRONMENT_ERROR"]:
            record_reproduction(tf, "1", "2026-01-01", 1, status, 1)
            data = json.loads(tf.read_text())
            assert data["bug_1"]["reproduction_status"] == status


class TestCreateReproductionFilename:
    def test_format(self, tmp_path):
        path = create_reproduction_filename(tmp_path, "12345", "Test Bug Title", 1)
        name = path.name
        assert "12345" in name
        assert "test_bug_title" in name
        assert "_1.md" in name

    def test_path_in_output_dir(self, tmp_path):
        path = create_reproduction_filename(tmp_path, "1", "title", 1)
        assert path.parent == tmp_path


class TestFindPreviousReproductions:
    def test_empty_dir(self, tmp_path):
        result = find_previous_reproductions(tmp_path, "999")
        assert result == []

    def test_finds_matching_files(self, tmp_path):
        for seq in [1, 2]:
            (tmp_path / f"reproduction_42_title_20260101_000000_{seq}.md").write_text("")
        result = find_previous_reproductions(tmp_path, "42")
        assert len(result) == 2
