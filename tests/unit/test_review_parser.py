"""Unit tests for devstack-test-agent/review_parser.py."""
from pathlib import Path
from review_parser import parse_review_file, get_review_timestamp, should_test_review, ReviewInfo


_DEFAULT_CONTENT = "# Review\n\n**Gerrit URL**: https://review.opendev.org/c/openstack/octavia/+/982615\n"


def _make_review_file(tmp_path, filename, content=_DEFAULT_CONTENT):
    f = tmp_path / filename
    f.write_text(content)
    return f


class TestParseReviewFile:
    def test_valid_filename_parsed(self, tmp_path):
        f = _make_review_file(
            tmp_path,
            "review_openstack_octavia_982615_ps1_20260331_133739.md"
        )
        info = parse_review_file(f)
        assert info is not None
        assert info.repo_name == "openstack/octavia"
        assert info.change_number == "982615"
        assert info.patchset == 1

    def test_hyphenated_repo(self, tmp_path):
        f = _make_review_file(
            tmp_path,
            "review_openstack_octavia-lib_942691_ps2_20260326_150116.md"
        )
        info = parse_review_file(f)
        assert info is not None
        assert info.change_number == "942691"
        assert info.patchset == 2

    def test_invalid_filename_returns_none(self, tmp_path):
        f = tmp_path / "notareview.md"
        f.write_text("content")
        assert parse_review_file(f) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert parse_review_file(tmp_path / "nope.md") is None

    def test_gerrit_url_extracted_from_content(self, tmp_path):
        f = _make_review_file(
            tmp_path,
            "review_openstack_octavia_982615_ps1_20260331_133739.md",
            "**Gerrit URL**: https://review.opendev.org/c/openstack/octavia/+/982615\n"
        )
        info = parse_review_file(f)
        assert info.gerrit_url == "https://review.opendev.org/c/openstack/octavia/+/982615"

    def test_default_gerrit_url_when_not_in_content(self, tmp_path):
        f = _make_review_file(
            tmp_path,
            "review_openstack_octavia_982615_ps1_20260331_133739.md",
            "# Review\n\nNo Gerrit URL here."
        )
        info = parse_review_file(f)
        assert "982615" in info.gerrit_url

    def test_already_tested_detected(self, tmp_path):
        f = _make_review_file(
            tmp_path,
            "review_openstack_octavia_982615_ps1_20260331_133739.md",
            "# Review\n\n### DevStack Integration Tests\nPASS"
        )
        info = parse_review_file(f)
        assert info.already_tested is True

    def test_not_already_tested(self, tmp_path):
        f = _make_review_file(
            tmp_path,
            "review_openstack_octavia_982615_ps1_20260331_133739.md",
        )
        info = parse_review_file(f)
        assert info.already_tested is False


class TestGetReviewTimestamp:
    def test_extracts_from_filename(self, tmp_path):
        f = tmp_path / "review_openstack_octavia_982615_ps1_20260331_133739.md"
        f.write_text("")
        ts = get_review_timestamp(f)
        assert "20260331" in ts
        assert "133739" in ts

    def test_returns_last_two_parts(self, tmp_path):
        f = tmp_path / "review_openstack_octavia_982615_ps1_20260331_133739.md"
        f.write_text("")
        ts = get_review_timestamp(f)
        assert ts == "20260331_133739"


class TestShouldTestReview:
    def _info(self, repo="openstack/octavia", change="982615", already_tested=False):
        return ReviewInfo(
            review_file=Path("/tmp/review.md"),
            repo_name=repo,
            change_number=change,
            patchset=1,
            gerrit_url="https://example.com",
            review_timestamp="20260331_133739",
            already_tested=already_tested,
        )

    def test_unfiltered_repo_should_test(self):
        assert should_test_review(self._info(), allowed_repos=[]) is True

    def test_already_tested_should_not_test(self):
        assert should_test_review(self._info(already_tested=True), allowed_repos=[]) is False

    def test_repo_in_allowed_list(self):
        assert should_test_review(self._info(), allowed_repos=["openstack/octavia"]) is True

    def test_repo_not_in_allowed_list(self):
        assert should_test_review(self._info(), allowed_repos=["openstack/neutron"]) is False

    def test_python_octaviaclient_skipped(self):
        info = self._info(repo="openstack/python-octaviaclient")
        assert should_test_review(info, allowed_repos=[]) is False

    def test_tempest_plugin_skipped(self):
        info = self._info(repo="openstack/octavia-tempest-plugin")
        assert should_test_review(info, allowed_repos=[]) is False

    def test_empty_allowed_repos_allows_all(self):
        info = self._info(repo="openstack/some-other-project")
        assert should_test_review(info, allowed_repos=[]) is True
