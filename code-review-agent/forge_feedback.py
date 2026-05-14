"""
Backward-compatibility shim.

forge_feedback utilities have moved to agents_lib.agents_lib.forge_feedback
so the DevStack Test and CI Failure agents can use them without duplicating code.
Existing imports from this module continue to work unchanged.
"""
from agents_lib.forge_feedback import (  # noqa: F401
    extract_forge_comment,
    extract_line_comments,
    determine_vote,
    extract_ci_forge_comment,
    extract_devstack_forge_comment,
)
