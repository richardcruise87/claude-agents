"""
Common report assembly framework.

Python — not the AI — writes every final report.  The AI returns its analysis
as section-marked text; Python parses those sections, fills a template, and
applies default values for any sections the AI did not provide.

AI output convention
--------------------
The prompt instructs the AI to wrap each analysis section with HTML-style markers:

    <!-- SECTION:section_name -->
    Content for this section
    <!-- /SECTION -->

Python convention
-----------------
Report templates use ``{{SECTION:name}}`` placeholders that are replaced by
``build_report()``.  Metadata fields (bug number, timestamp, etc.) continue
to use ``{UPPERCASE}`` placeholders filled by Python before the AI call.
"""

import re
from dataclasses import dataclass
from typing import Dict, List


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ReportSection:
    """Definition of a single report section.

    Args:
        name:     Section identifier — must match the marker name in the
                  template and in the AI's ``<!-- SECTION:name -->`` output.
        default:  Content used when the AI did not provide this section.
        required: When True and the section is missing AND has no default
                  (i.e. default is explicitly set to ``None``), ``build_report``
                  raises ``ValueError``.
    """

    name: str
    default: str = "Agent provided no data"
    required: bool = True


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(
    r"<!--\s*SECTION:(\w+)\s*-->(.*?)<!--\s*/SECTION\s*-->",
    re.DOTALL,
)


def parse_section_markers(text: str) -> Dict[str, str]:
    """Extract ``<!-- SECTION:name -->…<!-- /SECTION -->`` blocks from text.

    Returns a dict mapping section name → content (stripped of leading/
    trailing whitespace).  Sections absent from the text are not included;
    callers should apply defaults via :func:`build_report`.

    Args:
        text: AI response text (or any string containing section markers).

    Returns:
        ``{"section_name": "content", …}``
    """
    return {m.group(1): m.group(2).strip() for m in _SECTION_RE.finditer(text)}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_report(
    template: str,
    sections: Dict[str, str],
    section_defs: List[ReportSection],
) -> str:
    """Fill ``{{SECTION:name}}`` placeholders in *template* with content.

    For each :class:`ReportSection` in *section_defs*:
    - If the section name appears in *sections*, use that content.
    - Otherwise use ``section_def.default``.
    - If ``required=True`` and ``default`` is ``None``, raise ``ValueError``.

    Placeholders that do not correspond to any section_def are left unchanged
    so that metadata placeholders filled elsewhere are not disturbed.

    Args:
        template:     Report template string containing ``{{SECTION:name}}``
                      markers.
        sections:     Dict of section name → content, typically from
                      :func:`parse_section_markers`.
        section_defs: List of :class:`ReportSection` objects defining the
                      expected sections and their defaults.

    Returns:
        The assembled report string.

    Raises:
        ValueError: If a required section has no content and ``default=None``.
    """
    result = template
    for sec in section_defs:
        content = sections.get(sec.name)
        if content is None:
            if sec.required and sec.default is None:
                raise ValueError(
                    f"Required report section '{sec.name}' is missing and has no default."
                )
            content = sec.default if sec.default is not None else ""
        placeholder = "{{SECTION:" + sec.name + "}}"
        result = result.replace(placeholder, content)
    return result


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def section_prompt_instructions(section_defs: List[ReportSection]) -> str:
    """Return a formatted instruction block for inclusion in AI prompts.

    Generates the "how to return your analysis" instructions that tell the AI
    which sections to provide and how to format them.

    Args:
        section_defs: Sections the AI should fill.

    Returns:
        Markdown-formatted instruction string ready to embed in a prompt.
    """
    lines = [
        "Return your analysis using **section markers** — do NOT use the Write "
        "tool for the main report (Python will assemble and save it).",
        "",
        "For each section below, wrap your content like this:",
        "",
        "```",
        "<!-- SECTION:section_name -->",
        "Your content here",
        "<!-- /SECTION -->",
        "```",
        "",
        "Required sections:",
    ]
    for sec in section_defs:
        req = "" if sec.required else " *(optional)*"
        lines.append(f"- `{sec.name}`{req}")
    lines += [
        "",
        "If you cannot determine content for a section, include the marker with "
        "a brief explanation rather than omitting it entirely.",
    ]
    return "\n".join(lines)
