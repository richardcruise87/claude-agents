"""Unit tests for format_commit_info() in agents_lib.git_info."""
from agents_lib.git_info import format_commit_info


def _info(**overrides):
    """Return a minimal valid commit info dict, optionally overriding fields."""
    base = {
        "sha": "3d0aefdebb4de7e8ef80821fe8e7ce91a982e92f",
        "short_sha": "3d0aefde",
        "author": "Ghanshyam Maan <gmaan@example.com>",
        "date": "2026-06-02 18:49:39 +0000",
        "subject": "Drop python 3.10",
        "body": "",
        "change_id": "",
        "bug_refs": [],
        "error": "",
    }
    base.update(overrides)
    return base


class TestFormatCommitInfoChangeId:
    """Change-Id must appear exactly once regardless of commit body content."""

    def test_change_id_appears_once_when_in_body_and_extracted(self):
        # Regression: body already contains the Change-Id trailer; the structured
        # field below must not duplicate it.
        body = (
            "Due to constraints update in requirements, Tempest stopped\n"
            "working on python 3.10.\n\n"
            "Change-Id: I8ab344604d4b8a2fee9aa75502f575c9f9e9222b\n"
            "Signed-off-by: Ghanshyam Maan <gmaan@example.com>"
        )
        result = format_commit_info(_info(
            body=body,
            change_id="I8ab344604d4b8a2fee9aa75502f575c9f9e9222b",
        ))
        assert result.count("Change-Id:") == 1

    def test_change_id_value_is_correct(self):
        body = "Some description.\n\nChange-Id: Iabc123def456\n"
        result = format_commit_info(_info(body=body, change_id="Iabc123def456"))
        assert "Iabc123def456" in result
        assert result.count("Iabc123def456") == 1

    def test_change_id_only_body_appears_once(self):
        # Edge case: body consists solely of the Change-Id trailer (no prose).
        # The body section should be suppressed; Change-Id shown once in the
        # structured field.
        result = format_commit_info(_info(
            body="Change-Id: Iabc123def456",
            change_id="Iabc123def456",
        ))
        assert result.count("Change-Id:") == 1

    def test_no_change_id_shows_none(self):
        result = format_commit_info(_info(body="Just a description.", change_id=""))
        assert "Change-Id:" not in result

    def test_change_id_without_body_shows_once(self):
        # Commit with no body but a Change-Id extracted by the pre-flight.
        result = format_commit_info(_info(body="", change_id="Ideadbeef"))
        assert result.count("Change-Id:") == 1
        assert "Ideadbeef" in result


class TestFormatCommitInfoBody:
    """Body prose is preserved; only the Change-Id trailer is stripped."""

    def test_prose_description_preserved(self):
        body = (
            "This fixes the TLS cipher ordering bug.\n\n"
            "Change-Id: Ifoo\n"
            "Signed-off-by: Test User <t@t.com>"
        )
        result = format_commit_info(_info(body=body, change_id="Ifoo"))
        assert "TLS cipher ordering bug" in result

    def test_signed_off_by_preserved(self):
        body = "Description.\n\nChange-Id: Ifoo\nSigned-off-by: Test User <t@t.com>"
        result = format_commit_info(_info(body=body, change_id="Ifoo"))
        assert "Signed-off-by" in result

    def test_empty_body_no_blank_line_inserted(self):
        result = format_commit_info(_info(body="", change_id=""))
        # Without body or Change-Id only the four header fields should be present
        assert "Subject: Drop python 3.10" in result
        # No trailing blank line artefacts
        assert not result.endswith("\n\n")

    def test_body_only_change_id_section_suppressed(self):
        # When prose is empty after stripping Change-Id, the body block is omitted
        # entirely — no double blank line in the output.
        result = format_commit_info(_info(
            body="Change-Id: Ifoo",
            change_id="Ifoo",
        ))
        assert "\n\n\n" not in result


class TestFormatCommitInfoBugRefs:
    def test_bug_refs_included(self):
        result = format_commit_info(_info(bug_refs=["1234567", "9999999"]))
        assert "#1234567" in result
        assert "#9999999" in result

    def test_no_bug_refs_section_omitted(self):
        result = format_commit_info(_info(bug_refs=[]))
        assert "Bug refs" not in result


class TestFormatCommitInfoError:
    def test_error_returns_message_not_fields(self):
        result = format_commit_info(_info(error="git log failed (exit 128)"))
        assert "git commit info unavailable" in result
        assert "git log failed" in result
        assert "SHA:" not in result
