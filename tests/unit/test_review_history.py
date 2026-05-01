"""Unit tests for agents_lib.review_history."""
from agents_lib.forge_client import ChangeInfo
from agents_lib.review_history import (
    should_review_change,
    record_review,
    create_review_filename,
    find_previous_reviews,
    load_review_history,
    load_previous_review_context,
    _tracking_key,
)


def _gerrit_change(**kwargs):
    defaults = dict(
        change_id="982567", repo_name="openstack/octavia", title="Fix bug",
        branch="master", created_at="2026-03-01T10:00:00", updated_at="2026-03-30T12:00:00",
        head_sha="abc123", patchset=1, git_fetch_ref="refs/changes/67/982567/1",
        forge_url="https://review.opendev.org/c/openstack/octavia/+/982567",
        author="Alice", forge_type="gerrit",
    )
    defaults.update(kwargs)
    return ChangeInfo(**defaults)


def _github_change(**kwargs):
    defaults = dict(
        change_id="123", repo_name="owner/repo", title="Fix PR",
        branch="main", created_at="2026-03-01T10:00:00", updated_at="2026-03-30T12:00:00",
        head_sha="deadbeef", patchset=None, git_fetch_ref="refs/pull/123/head",
        forge_url="https://github.com/owner/repo/pull/123",
        author="Bob", forge_type="github",
    )
    defaults.update(kwargs)
    return ChangeInfo(**defaults)


# ---------------------------------------------------------------------------
# _tracking_key
# ---------------------------------------------------------------------------

class TestTrackingKey:
    def test_gerrit_key_includes_patchset(self):
        key = _tracking_key(_gerrit_change(patchset=3))
        assert "ps3" in key
        assert "982567" in key

    def test_github_key_uses_sha(self):
        key = _tracking_key(_github_change(head_sha="deadbeefcafe1234"))
        assert "123" in key
        assert "deadbeef" in key   # first 8 chars
        assert "ps" not in key

    def test_different_patchsets_different_keys(self):
        k1 = _tracking_key(_gerrit_change(patchset=1))
        k2 = _tracking_key(_gerrit_change(patchset=2))
        assert k1 != k2

    def test_different_shas_different_keys(self):
        k1 = _tracking_key(_github_change(head_sha="aaaa1111"))
        k2 = _tracking_key(_github_change(head_sha="bbbb2222"))
        assert k1 != k2


# ---------------------------------------------------------------------------
# should_review_change
# ---------------------------------------------------------------------------

class TestShouldReviewChange:
    def test_never_reviewed(self):
        should, seq = should_review_change(_gerrit_change(), {})
        assert should is True
        assert seq == 1

    def test_already_reviewed_same_patchset(self, tmp_path):
        change = _gerrit_change(patchset=1)
        tf = tmp_path / "t.json"
        record_review(tf, change, 1, tmp_path / "review.md")
        history = load_review_history(tf)
        should, seq = should_review_change(change, history)
        assert should is False
        assert seq == 1

    def test_new_gerrit_patchset_triggers_rereview(self, tmp_path):
        tf = tmp_path / "t.json"
        record_review(tf, _gerrit_change(patchset=1), 1, tmp_path / "r1.md")
        history = load_review_history(tf)
        should, seq = should_review_change(_gerrit_change(patchset=2), history)
        assert should is True
        assert seq == 2

    def test_new_github_sha_triggers_rereview(self, tmp_path):
        tf = tmp_path / "t.json"
        record_review(tf, _github_change(head_sha="aaaa0000"), 1, tmp_path / "r1.md")
        history = load_review_history(tf)
        should, seq = should_review_change(_github_change(head_sha="bbbb1111"), history)
        assert should is True
        assert seq == 2

    def test_same_github_sha_no_rereview(self, tmp_path):
        tf = tmp_path / "t.json"
        change = _github_change(head_sha="deadbeef")
        record_review(tf, change, 1, tmp_path / "r1.md")
        history = load_review_history(tf)
        should, seq = should_review_change(change, history)
        assert should is False

    def test_sequence_increments_correctly(self, tmp_path):
        tf = tmp_path / "t.json"
        record_review(tf, _github_change(head_sha="sha1"), 1, tmp_path / "r1.md")
        record_review(tf, _github_change(head_sha="sha2"), 2, tmp_path / "r2.md")
        history = load_review_history(tf)
        should, seq = should_review_change(_github_change(head_sha="sha3"), history)
        assert should is True
        assert seq == 3


# ---------------------------------------------------------------------------
# create_review_filename
# ---------------------------------------------------------------------------

class TestCreateReviewFilename:
    def test_gerrit_backward_compat_format(self, tmp_path):
        path = create_review_filename(tmp_path, _gerrit_change(patchset=2), 1, "20260330_143000")
        assert "ps2" in path.name
        assert "982567" in path.name
        assert path.name.endswith(".md")

    def test_github_uses_sequence(self, tmp_path):
        path = create_review_filename(tmp_path, _github_change(), 3, "20260330_143000")
        assert "r3" in path.name
        assert "123" in path.name
        assert "ps" not in path.name

    def test_gitlab_uses_sequence(self, tmp_path):
        change = _github_change(forge_type="gitlab", change_id="456")
        path = create_review_filename(tmp_path, change, 2, "ts")
        assert "r2" in path.name

    def test_path_in_output_dir(self, tmp_path):
        path = create_review_filename(tmp_path, _gerrit_change(), 1, "ts")
        assert path.parent == tmp_path


# ---------------------------------------------------------------------------
# find_previous_reviews
# ---------------------------------------------------------------------------

class TestFindPreviousReviews:
    def test_empty_dir(self, tmp_path):
        assert find_previous_reviews(tmp_path, _gerrit_change()) == []

    def test_finds_matching_files(self, tmp_path):
        import time
        f1 = tmp_path / "review_openstack_octavia_982567_ps1_20260101_000000.md"
        f1.write_text("")
        time.sleep(0.05)
        f2 = tmp_path / "review_openstack_octavia_982567_ps2_20260201_000000.md"
        f2.write_text("")
        results = find_previous_reviews(tmp_path, _gerrit_change())
        assert len(results) == 2
        assert results[0] == f1  # oldest first

    def test_github_finds_by_pr_number(self, tmp_path):
        (tmp_path / "review_owner_repo_123_r1_20260101_000000.md").write_text("")
        results = find_previous_reviews(tmp_path, _github_change())
        assert len(results) == 1


# ---------------------------------------------------------------------------
# load_previous_review_context
# ---------------------------------------------------------------------------

class TestLoadPreviousReviewContext:
    def test_returns_none_when_no_history(self, tmp_path):
        content, record = load_previous_review_context(tmp_path, _gerrit_change(), {})
        assert content is None
        assert record is None

    def test_returns_content_and_record(self, tmp_path):
        change = _gerrit_change()
        tf = tmp_path / "t.json"
        review_file = tmp_path / "review_openstack_octavia_982567_ps1_20260101_000000.md"
        review_file.write_text("# Review\n\nPrevious review content here.")
        record_review(tf, change, 1, review_file)
        history = load_review_history(tf)

        content, rec = load_previous_review_context(tmp_path, change, history)
        # Should NOT find the file since the key in history is for ps1 which
        # equals the current change — this tests we find the latest prior record
        assert rec is not None
        assert rec.sequence == 1
