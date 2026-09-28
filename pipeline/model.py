"""
Turns the raw (candidate, events) rows from the DB into a convenient
in-memory view used by both the pipeline UI and the search engine.
"""
from datetime import datetime, timezone
from . import db
from .stages import STAGE_ORDER
from .timeutil import parse_iso as _parse


class CandidateView:
    """A read-only, derived snapshot of one candidate's state."""

    def __init__(self, candidate_row, events):
        self.id = candidate_row["id"]
        self.name = candidate_row["name"]
        self.created_at = candidate_row["created_at"]
        self.events = events  # full ordered history, oldest first

        last = events[-1]
        self.current_stage = last["to_stage"]
        self.stage_since = last["at"]  # when it entered the current stage

        # Every stage this candidate has ever been moved into (order preserved).
        self.stages_reached = []
        seen = set()
        for e in events:
            if e["to_stage"] not in seen:
                seen.add(e["to_stage"])
                self.stages_reached.append(e["to_stage"])

        # Timestamp of the event that first moved them into each stage.
        self.reached_at = {}
        for e in events:
            if e["to_stage"] not in self.reached_at:
                self.reached_at[e["to_stage"]] = e["at"]

    @property
    def is_rejected(self):
        return self.current_stage == "Rejected"

    @property
    def is_hired(self):
        return self.current_stage == "Hired"

    def time_in_current_stage(self, now=None):
        now = now or datetime.now(timezone.utc)
        return now - _parse(self.stage_since)

    def reached(self, stage):
        return stage in self.stages_reached

    def reached_before_current(self, stage):
        """True if the candidate passed through `stage` at some point but is
        no longer there (used for 'reached Offer but not Hired' style
        queries)."""
        return stage in self.stages_reached and self.current_stage != stage

    def to_dict(self, include_history=False):
        d = {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "current_stage": self.current_stage,
            "stage_since": self.stage_since,
            "days_in_stage": round(self.time_in_current_stage().total_seconds() / 86400, 2),
        }
        if include_history:
            d["history"] = [
                {
                    "event_type": e["event_type"],
                    "from_stage": e["from_stage"],
                    "to_stage": e["to_stage"],
                    "at": e["at"],
                    "note": e["note"],
                }
                for e in self.events
            ]
        return d


def load_all_candidates():
    """Returns a list of CandidateView, newest-created first is NOT assumed;
    callers sort as needed."""
    candidates = db.get_all_candidates()
    all_events = db.get_all_events()
    by_candidate = {}
    for e in all_events:
        by_candidate.setdefault(e["candidate_id"], []).append(e)

    views = []
    for c in candidates:
        events = by_candidate.get(c["id"], [])
        if not events:
            continue
        views.append(CandidateView(c, events))
    return views


def load_candidate(candidate_id):
    c = db.get_candidate(candidate_id)
    if not c:
        return None
    events = db.get_events(candidate_id)
    if not events:
        return None
    return CandidateView(c, events)


def group_by_stage(views):
    groups = {s: [] for s in STAGE_ORDER + ["Rejected"]}
    for v in views:
        groups.setdefault(v.current_stage, []).append(v)
    return groups
