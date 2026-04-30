"""Unit tests for code-review-agent/patchset_tracker.py.

Migrates and extends the assertions from the old code-review-agent/test_*.py files.
"""
from patchset_tracker import (
    find_previous_reviews,
    get_latest_review,
    create_review_filename,
    load_previous_review,
    extract_patchset_from_review,
    rename_review_with_patchset,
)


def _make_review(tmp_path, name, content="# Review\n**Patchset**: 1\n"):
    f = tmp_path / name
    f.write_text(content)
    return f


class TestFindPreviousReviews:
    def test_empty_dir(self, tmp_path):
        result = find_previous_reviews(tmp_path, "openstack/octavia", "982615")
        assert result == []

    def test_finds_matching_files(self, tmp_path):
        _make_review(tmp_path, "review_openstack_octavia_982615_ps1_20260101_000000.md")
        _make_review(tmp_path, "review_openstack_octavia_982615_ps2_20260201_000000.md")
        result = find_previous_reviews(tmp_path, "openstack/octavia", "982615")
        assert len(result) == 2

    def test_does_not_match_other_changes(self, tmp_path):
        _make_review(tmp_path, "review_openstack_octavia_982615_ps1_20260101_000000.md")
        _make_review(tmp_path, "review_openstack_octavia_999999_ps1_20260101_000000.md")
        result = find_previous_reviews(tmp_path, "openstack/octavia", "982615")
        assert all("982615" in p.name for p in result)

    def test_sorted_by_mtime(self, tmp_path):
        import time
        f1 = _make_review(tmp_path, "review_openstack_octavia_982615_ps1_20260101_000000.md")
        time.sleep(0.05)
        f2 = _make_review(tmp_path, "review_openstack_octavia_982615_ps2_20260201_000000.md")
        result = find_previous_reviews(tmp_path, "openstack/octavia", "982615")
        assert result[0] == f1
        assert result[-1] == f2


class TestGetLatestReview:
    def test_returns_none_when_empty(self, tmp_path):
        assert get_latest_review(tmp_path, "openstack/octavia", "982615") is None

    def test_returns_most_recent(self, tmp_path):
        import time
        _make_review(tmp_path, "review_openstack_octavia_982615_ps1_20260101_000000.md")
        time.sleep(0.05)
        f2 = _make_review(tmp_path, "review_openstack_octavia_982615_ps2_20260201_000000.md")
        result = get_latest_review(tmp_path, "openstack/octavia", "982615")
        assert result == f2


class TestCreateReviewFilename:
    def test_format(self, tmp_path):
        path = create_review_filename(tmp_path, "openstack/octavia", "982615", 2, "20260330_143000")
        name = path.name
        assert name.startswith("review_openstack_octavia_982615_ps2_")
        assert "20260330_143000" in name
        assert name.endswith(".md")

    def test_path_in_output_dir(self, tmp_path):
        path = create_review_filename(tmp_path, "openstack/octavia", "1", 1, "20260101_000000")
        assert path.parent == tmp_path

    def test_repo_slash_converted(self, tmp_path):
        path = create_review_filename(tmp_path, "openstack/octavia-lib", "1", 1, "ts")
        assert "/" not in path.name


class TestLoadPreviousReview:
    def test_returns_content(self, tmp_path):
        f = tmp_path / "review.md"
        f.write_text("# Review content\n\nBody here.")
        content = load_previous_review(f)
        assert "Review content" in content


class TestExtractPatchsetFromReview:
    def test_bold_patchset_format(self):
        content = "**Patchset**: 3\nOther content."
        result = extract_patchset_from_review(content)
        assert result == 3

    def test_ps_prefix_format(self):
        content = "Patchset PS 5 reviewed."
        result = extract_patchset_from_review(content)
        assert result == 5

    def test_ps_underscore_in_filename(self):
        content = "review_openstack_octavia_982615_ps2_20260101.md was reviewed."
        result = extract_patchset_from_review(content)
        assert result == 2

    def test_returns_none_when_not_found(self):
        result = extract_patchset_from_review("No patchset information here.")
        assert result is None


class TestRenameReviewWithPatchset:
    def test_no_rename_when_already_has_patchset(self, tmp_path):
        f = tmp_path / "review_openstack_octavia_982615_ps2_20260101_000000.md"
        f.write_text("")
        result = rename_review_with_patchset(f, 2)
        assert result == f

    def test_adds_patchset_to_legacy_name(self, tmp_path):
        f = tmp_path / "review_openstack_octavia_982615_20260101_000000.md"
        f.write_text("")
        result = rename_review_with_patchset(f, 1)
        assert "ps1" in result.name

    def test_removes_latest_suffix(self, tmp_path):
        f = tmp_path / "review_openstack_octavia_982615_20260101_000000-latest.md"
        f.write_text("")
        result = rename_review_with_patchset(f, 1)
        assert "latest" not in result.name
