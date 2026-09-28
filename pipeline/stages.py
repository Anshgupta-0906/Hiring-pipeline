"""
Stage definitions and transition rules for the hiring pipeline.

Pipeline: Applied -> Screening -> Interview -> Offer -> Hired
A candidate can be Rejected from any active stage, but never after Hired,
and Hired/Rejected are terminal (final) states that can never be reversed.
"""

# Canonical, ordered list of the "active" stages a candidate walks through.
STAGE_ORDER = ["Applied", "Screening", "Interview", "Offer", "Hired"]

# Terminal states that are not part of the forward progression.
TERMINAL_STATES = ["Rejected"]

ALL_STAGES = STAGE_ORDER + TERMINAL_STATES

# Case-insensitive lookup: "screening" -> "Screening"
_STAGE_LOOKUP = {s.lower(): s for s in ALL_STAGES}


class InvalidTransition(Exception):
    """Raised when a requested stage move breaks the pipeline's rules."""
    pass


def normalize_stage(name):
    """Return the canonical-cased stage name, or None if unrecognized."""
    if name is None:
        return None
    return _STAGE_LOOKUP.get(name.strip().lower())


def is_terminal(stage):
    return stage in TERMINAL_STATES


def next_stage(current_stage):
    """The single next stage after `current_stage` in the forward pipeline,
    or None if `current_stage` is Hired (nothing comes after) or unknown."""
    if current_stage not in STAGE_ORDER:
        return None
    idx = STAGE_ORDER.index(current_stage)
    if idx + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[idx + 1]


def validate_advance(current_stage):
    """Validate that a candidate at `current_stage` may be advanced one step.
    Returns the destination stage, or raises InvalidTransition with a
    human-readable reason."""
    if current_stage == "Hired":
        raise InvalidTransition(
            "This candidate has already been hired. Hired is a final "
            "outcome and cannot be changed."
        )
    if current_stage == "Rejected":
        raise InvalidTransition(
            "This candidate has been rejected. Rejected is a final outcome "
            "and cannot be reversed."
        )
    dest = next_stage(current_stage)
    if dest is None:
        raise InvalidTransition(
            f"There is no stage after '{current_stage}'."
        )
    return dest


def validate_reject(current_stage):
    """Validate that a candidate at `current_stage` may be rejected.
    Raises InvalidTransition if not."""
    if current_stage == "Hired":
        raise InvalidTransition(
            "This candidate has already been hired and cannot be rejected. "
            "Hired is a final outcome."
        )
    if current_stage == "Rejected":
        raise InvalidTransition(
            "This candidate has already been rejected."
        )
    return "Rejected"
