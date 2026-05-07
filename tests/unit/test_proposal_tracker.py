"""Unit tests for fix-proposal-agent/proposal_tracker.py."""
from proposal_tracker import (
    create_proposal_filename,
    find_previous_proposals,
    load_proposal_history,
    read_local_feedback,
    record_proposal,
    should_propose_fix,
)


_TS_OLD = "2026-05-01T10:00:00"
_TS_NEW = "2026-05-07T10:00:00"


class TestShouldProposeFix:
    def test_new_bug_should_propose(self):
        should, seq = should_propose_fix("12345", _TS_NEW, {})
        assert should is True
        assert seq == 1

    def test_same_triage_timestamp_should_not_propose(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_proposal(tracking, "12345", _TS_NEW, 1, tmp_path / "p.md")
        history = load_proposal_history(tracking)
        should, seq = should_propose_fix("12345", _TS_NEW, history)
        assert should is False

    def test_newer_triage_triggers_reproposal(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_proposal(tracking, "12345", _TS_OLD, 1, tmp_path / "p.md")
        history = load_proposal_history(tracking)
        should, seq = should_propose_fix("12345", _TS_NEW, history)
        assert should is True
        assert seq == 2

    def test_different_bugs_are_independent(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_proposal(tracking, "11111", _TS_NEW, 1, tmp_path / "p.md")
        history = load_proposal_history(tracking)
        should, seq = should_propose_fix("22222", _TS_NEW, history)
        assert should is True
        assert seq == 1


class TestRecordProposal:
    def test_creates_entry(self, tmp_path):
        tracking = tmp_path / "track.json"
        proposal_file = tmp_path / "fix_proposal_12345_title_20260507_1.md"
        record_proposal(tracking, "12345", _TS_NEW, 1, proposal_file)
        history = load_proposal_history(tracking)
        assert "fix_12345" in history
        entry = history["fix_12345"]
        assert entry["sequence"] == 1
        assert entry["status"] == "proposed"
        assert str(proposal_file) in entry["proposal_file"]

    def test_gerrit_change_id_stored_when_given(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_proposal(
            tracking, "12345", _TS_NEW, 1, tmp_path / "p.md",
            gerrit_change_id="987654",
        )
        history = load_proposal_history(tracking)
        assert history["fix_12345"]["gerrit_change_id"] == "987654"

    def test_custom_status_stored(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_proposal(
            tracking, "12345", _TS_NEW, 1, tmp_path / "p.md", status="accepted"
        )
        history = load_proposal_history(tracking)
        assert history["fix_12345"]["status"] == "accepted"


class TestCreateProposalFilename:
    def test_format(self, tmp_path):
        path = create_proposal_filename(tmp_path, "2146764", "TLS cipher issue", 1)
        assert path.name.startswith("fix_proposal_2146764_")
        assert path.name.endswith("_1.md")
        assert path.parent == tmp_path

    def test_title_slugified(self, tmp_path):
        path = create_proposal_filename(tmp_path, "99", "Load balancer fails!", 2)
        assert "load_balancer_fails" in path.name
        assert path.name.endswith("_2.md")


class TestFindPreviousProposals:
    def test_empty_dir(self, tmp_path):
        assert find_previous_proposals(tmp_path, "12345") == []

    def test_finds_matching_files(self, tmp_path):
        (tmp_path / "fix_proposal_12345_title_20260507_143022_1.md").write_text("")
        (tmp_path / "fix_proposal_12345_title_20260507_150000_2.md").write_text("")
        results = find_previous_proposals(tmp_path, "12345")
        assert len(results) == 2
        assert results[0].stem.endswith("_1")
        assert results[1].stem.endswith("_2")

    def test_excludes_context_files(self, tmp_path):
        (tmp_path / "fix_proposal_12345_title_20260507_143022_1.md").write_text("")
        (tmp_path / "fix_proposal_12345_context.md").write_text("")
        results = find_previous_proposals(tmp_path, "12345")
        assert len(results) == 1

    def test_does_not_match_other_bugs(self, tmp_path):
        (tmp_path / "fix_proposal_12345_title_20260507_143022_1.md").write_text("")
        (tmp_path / "fix_proposal_99999_title_20260507_143022_1.md").write_text("")
        results = find_previous_proposals(tmp_path, "12345")
        assert len(results) == 1


class TestReadLocalFeedback:
    def test_returns_none_when_no_file(self, tmp_path):
        assert read_local_feedback("12345", tmp_path) is None

    def test_returns_content_and_deletes_file(self, tmp_path):
        f = tmp_path / "fix_proposal_12345_feedback.txt"
        f.write_text("Please make the fix more targeted.")
        result = read_local_feedback("12345", tmp_path)
        assert result == "Please make the fix more targeted."
        assert not f.exists()

    def test_returns_none_for_empty_file(self, tmp_path):
        (tmp_path / "fix_proposal_12345_feedback.txt").write_text("   ")
        assert read_local_feedback("12345", tmp_path) is None
