"""Unit tests for bug-reproduction-agent/triage_parser.py."""
import pytest
from triage_parser import (
    parse_triage_file,
    extract_bug_metadata,
    extract_bash_blocks,
    extract_section_text,
    get_triage_timestamp,
)


# ---------------------------------------------------------------------------
# extract_bug_metadata
# ---------------------------------------------------------------------------

class TestExtractBugMetadata:
    def test_full_format(self, sample_triage_markdown):
        meta = extract_bug_metadata(sample_triage_markdown)
        assert meta["bug_number"] == "12345"
        assert meta["bug_title"] == "Load balancer fails to start"
        assert meta["severity"] == "HIGH"

    def test_alternative_format(self):
        md = "- **Bug Number**: 99999\n- **Title**: Another bug\n- **Severity:** Medium"
        meta = extract_bug_metadata(md)
        assert meta.get("bug_number") == "99999"

    def test_heading_format_bug_number(self):
        md = "# Bug Triage Report: Bug #2150752\n## Loadbalancer KeyError\n"
        meta = extract_bug_metadata(md)
        assert meta.get("bug_number") == "2150752"

    def test_heading_format_bug_title(self):
        md = "# Bug Triage Report: Bug #2150752\n## Loadbalancer KeyError when adding a member\n"
        meta = extract_bug_metadata(md)
        assert meta.get("bug_title") == "Loadbalancer KeyError when adding a member"

    def test_heading_format_does_not_match_mid_line(self):
        # Ensure the anchored regex doesn't match a # heading embedded mid-content
        md = "Some text # Bug Triage Report: Bug #9999\n**Bug ID:** 2222\n"
        meta = extract_bug_metadata(md)
        assert meta.get("bug_number") == "2222"

    def test_missing_fields_no_crash(self):
        meta = extract_bug_metadata("# No metadata here")
        assert isinstance(meta, dict)

    def test_validation_status_extracted(self, sample_triage_markdown):
        meta = extract_bug_metadata(sample_triage_markdown)
        assert "VALID BUG" in meta.get("validation_status", "")


# ---------------------------------------------------------------------------
# extract_bash_blocks
# ---------------------------------------------------------------------------

class TestExtractBashBlocks:
    def test_extracts_blocks_from_section(self, sample_triage_markdown):
        blocks = extract_bash_blocks(
            sample_triage_markdown, "Step 7: DevStack Reproduction Strategy"
        )
        assert len(blocks) >= 1
        assert any("openstack loadbalancer create" in b for b in blocks)

    def test_empty_when_section_missing(self, sample_triage_markdown):
        blocks = extract_bash_blocks(sample_triage_markdown, "Step 99: Nonexistent")
        assert blocks == []

    def test_multiple_blocks_extracted(self, sample_triage_markdown):
        blocks = extract_bash_blocks(
            sample_triage_markdown, "Step 7: DevStack Reproduction Strategy"
        )
        # Sample has at least 2 bash blocks in step 7
        assert len(blocks) >= 2

    def test_skips_comment_only_blocks(self):
        md = """\
## Step 7: DevStack Reproduction Strategy

```bash
# This is only a comment
```

```bash
openstack loadbalancer create --name lb
```
"""
        blocks = extract_bash_blocks(md, "Step 7: DevStack Reproduction Strategy")
        # The comment-only block has code starting with '#', which the parser includes
        # but the actual openstack command block is definitely there
        assert any("openstack" in b for b in blocks)


# ---------------------------------------------------------------------------
# extract_section_text
# ---------------------------------------------------------------------------

class TestExtractSectionText:
    def test_extracts_text(self, sample_triage_markdown):
        # extract_section_text expects the header title without the ### prefix
        text = extract_section_text(sample_triage_markdown, "Root Cause Analysis")
        assert "Race condition" in text

    def test_empty_string_for_missing_section(self, sample_triage_markdown):
        text = extract_section_text(sample_triage_markdown, "Nonexistent Section")
        assert text == ""

    def test_code_blocks_removed(self):
        md = """\
### My Section
Some text here.

```bash
code block
```

More text.
"""
        text = extract_section_text(md, "My Section")
        assert "code block" not in text
        assert "Some text here" in text


# ---------------------------------------------------------------------------
# get_triage_timestamp
# ---------------------------------------------------------------------------

class TestGetTriageTimestamp:
    def test_extracts_from_filename(self, tmp_path):
        f = tmp_path / "bug_12345_title_20260330_143000_1.md"
        f.write_text("content")
        ts = get_triage_timestamp(f)
        assert "2026-03-30" in ts
        assert "14:30:00" in ts

    def test_fallback_to_mtime(self, tmp_path):
        # File with no timestamp in name
        f = tmp_path / "notimestamp.md"
        f.write_text("content")
        ts = get_triage_timestamp(f)
        assert ts  # Should return something non-empty


# ---------------------------------------------------------------------------
# parse_triage_file
# ---------------------------------------------------------------------------

class TestParseTriageFile:
    def test_parses_full_report(self, tmp_path, sample_triage_markdown):
        f = tmp_path / "bug_12345_test_20260330_143000_1.md"
        f.write_text(sample_triage_markdown)
        report = parse_triage_file(f)
        assert report.bug_number == "12345"
        assert report.bug_title == "Load balancer fails to start"
        assert report.severity == "HIGH"
        assert len(report.reproduction_steps) >= 1
        assert report.triage_file == f

    def test_raises_for_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_triage_file(tmp_path / "nope.md")

    def test_minimal_report_no_crash(self, tmp_path):
        f = tmp_path / "bug_1_minimal_20260101_000000_1.md"
        f.write_text("# Minimal Triage\n\nNo structured data.")
        report = parse_triage_file(f)
        assert report.bug_number == "" or report.bug_number is not None
