"""
Backward-compatibility shim.

forge_feedback utilities have moved to agents_lib.agents_lib.forge_feedback
so the DevStack Test and CI Failure agents can use them without duplicating code.
Existing imports from this module continue to work unchanged.

Note: extract_devstack_forge_comment is also re-exported here even though it
did not exist in the original module. This is intentional — any future code
in the code-review-agent directory that needs it can import from here rather
than directly from agents_lib, keeping import paths consistent within the agent.
"""
from agents_lib.forge_feedback import (  # noqa: F401
    extract_forge_comment,
    extract_line_comments,
    determine_vote,
    extract_ci_forge_comment,
    extract_devstack_forge_comment,
)
