"""
A small natural-language-ish search engine for the recruiter's search box.

Design:
  1. Scan the raw query text for recognizable *clauses* (stage filters,
     duration filters, date filters, "reached X but not hired", "except
     rejected", ...). Each recognized clause is stripped out of the text
     and turned into a predicate over a CandidateView.
  2. Whatever text is left after stripping clauses and stopwords is treated
     as a *name fragment* and fuzzy-matched against candidate names.
  3. All predicates are AND-ed together. Remaining candidates are then
     ranked: by name-similarity if a name fragment was given, otherwise by
     a sensible recency measure for whichever filter was used.
  4. If nothing could be understood at all, or a stage name is unknown, we
     explain *why* instead of silently returning an empty list.

This is intentionally a hand-rolled parser (regex + difflib) rather than a
full NLP stack -- the query vocabulary is narrow and closed, so a small set
of well-tested patterns covers the space described in the brief while
staying easy to extend.
"""
import re
import difflib
from datetime import datetime, timedelta, timezone

from .stages import ALL_STAGES, STAGE_ORDER
from .timeutil import parse_iso

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_STOPWORDS = {
    "who", "whos", "who's", "is", "are", "in", "the", "a", "an", "of", "to",
    "for", "right", "now", "currently", "and", "or", "everyone", "everybody",
    "all", "candidate", "candidates", "find", "show", "me", "list", "get",
    "please", "stage", "with", "who's", "has", "have", "been", "did",
    "didn't", "didnt", "not", "but", "got", "reached", "moved", "stuck",
    "since", "more", "than", "over", "at", "least", "except", "excluding",
    "without", "minus", "non", "rejected",
}

STAGE_PATTERN = "|".join(re.escape(s) for s in ALL_STAGES)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _word_number(word):
    words = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    if word.isdigit():
        return int(word)
    return words.get(word.lower())


def _unit_to_days(unit, n):
    unit = unit.lower().rstrip("s")
    if unit == "day":
        return n
    if unit == "week":
        return n * 7
    if unit == "month":
        return n * 30
    if unit == "hour":
        return n / 24
    return n


def best_stage_match(word):
    """Fuzzy-correct a single word/phrase to a known stage name.
    Returns (canonical_stage, exact: bool) or (None, False) if nothing is
    close enough to be a plausible attempt at a stage name."""
    word_l = word.strip().lower()
    for s in ALL_STAGES:
        if s.lower() == word_l:
            return s, True
    best, best_ratio = None, 0.0
    for s in ALL_STAGES:
        r = difflib.SequenceMatcher(None, word_l, s.lower()).ratio()
        if r > best_ratio:
            best, best_ratio = s, r
    if best_ratio >= 0.75:
        return best, False
    return None, False


def parse_date_phrase(phrase, today=None):
    """Best-effort parse of a trailing date phrase like 'Monday',
    'yesterday', 'last week', '3 days ago', '2024-06-01'.
    Returns a timezone-aware datetime (start of that day, UTC) or None."""
    today = today or datetime.now(timezone.utc)
    phrase = phrase.strip().lower().rstrip(".,!?")
    if not phrase:
        return None

    if phrase in ("today",):
        return today.replace(hour=0, minute=0, second=0, microsecond=0)
    if phrase in ("yesterday",):
        return (today - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if phrase in ("last week", "a week ago"):
        return today - timedelta(days=7)

    m = re.match(r"(\d+)\s*days?\s*ago", phrase)
    if m:
        return today - timedelta(days=int(m.group(1)))

    if phrase in WEEKDAYS:
        target = WEEKDAYS.index(phrase)
        delta = (today.weekday() - target) % 7
        d = today - timedelta(days=delta)
        return d.replace(hour=0, minute=0, second=0, microsecond=0)

    # ISO date: 2024-06-01
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", phrase)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None

    return None


def _name_similarity(query_fragment, name):
    """Fuzzy similarity between a typed fragment and a candidate's name,
    tolerant of typos and partial (first-name-only / last-name-only)
    queries. Returns a value in [0, 1]."""
    q = query_fragment.lower().strip()
    n = name.lower().strip()
    if not q:
        return 0.0
    if q in n:
        # substring match (typo-free partial name) - strong signal,
        # stronger the larger a fraction of the name it covers.
        return 0.85 + 0.15 * (len(q) / max(len(n), 1))

    whole_ratio = difflib.SequenceMatcher(None, q, n).ratio()

    # Compare the fragment against each token of the name too (so "sharam"
    # matches "Priya Sharma" via the token "Sharma", and single-word typo'd
    # first- or last-name searches still work).
    token_best = 0.0
    for token in n.split():
        token_best = max(token_best, difflib.SequenceMatcher(None, q, token).ratio())
        # also compare against each token of a multi-word query fragment
        for qtok in q.split():
            token_best = max(token_best, difflib.SequenceMatcher(None, qtok, token).ratio())

    return max(whole_ratio, token_best)


NAME_MATCH_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Clause extraction
# ---------------------------------------------------------------------------

class ParsedQuery:
    def __init__(self):
        self.filters = []          # list of (description, predicate_fn)
        self.rank_hint = None      # ('stage_duration'|'move_date'|None, stage)
        self.name_fragment = ""
        self.notes = []            # assumptions we made, shown to the recruiter
        self.errors = []           # hard problems (unknown stage, bad date, etc.)
        self.recognized_anything = False


def parse_query(text):
    pq = ParsedQuery()
    working = " " + text.strip() + " "

    # --- 1. "stuck in <stage> for (more than) N <unit>" ---------------------
    m = re.search(
        r"\bstuck\s+in\s+([a-zA-Z]+)\s+for\s+(?:more\s+than\s+|over\s+|at\s+least\s+)?"
        r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
        r"(day|days|week|weeks|month|months|hour|hours)\b",
        working, flags=re.IGNORECASE,
    )
    if m:
        pq.recognized_anything = True
        stage_word, num_word, unit = m.group(1), m.group(2), m.group(3)
        stage, exact = best_stage_match(stage_word)
        if stage is None:
            pq.errors.append(
                f"'{stage_word}' isn't a stage in this pipeline. Valid stages are: "
                + ", ".join(STAGE_ORDER) + " (plus Rejected)."
            )
        else:
            if not exact:
                pq.notes.append(f"Reading '{stage_word}' as the '{stage}' stage.")
            n = _word_number(num_word) or 1
            min_days = _unit_to_days(unit, n)

            def make_pred(stage=stage, min_days=min_days):
                def pred(c):
                    return c.current_stage == stage and c.time_in_current_stage().total_seconds() / 86400 >= min_days
                return pred

            pq.filters.append((f"stuck in {stage} for {n}+ {unit.rstrip('s')}(s)", make_pred()))
            pq.rank_hint = ("stage_duration", stage)
        working = working[: m.start()] + " " + working[m.end():]

    # --- 2. "moved to <stage> since <date phrase>" --------------------------
    m = re.search(
        r"\bmoved\s+to\s+([a-zA-Z]+)\s+since\s+([a-zA-Z0-9 \-]+?)(?=$|[.,;]| and \b)",
        working, flags=re.IGNORECASE,
    )
    if m:
        pq.recognized_anything = True
        stage_word, date_phrase = m.group(1), m.group(2)
        stage, exact = best_stage_match(stage_word)
        if stage is None:
            pq.errors.append(
                f"'{stage_word}' isn't a stage in this pipeline. Valid stages are: "
                + ", ".join(STAGE_ORDER) + "."
            )
        else:
            if not exact:
                pq.notes.append(f"Reading '{stage_word}' as the '{stage}' stage.")
            since_dt = parse_date_phrase(date_phrase)
            if since_dt is None:
                pq.errors.append(
                    f"I couldn't understand the date '{date_phrase.strip()}'. Try a weekday "
                    "name ('Monday'), 'yesterday', 'N days ago', or YYYY-MM-DD."
                )
            else:
                def make_pred(stage=stage, since_dt=since_dt):
                    def pred(c):
                        at = c.reached_at.get(stage)
                        if at is None:
                            return False
                        return parse_iso(at) >= since_dt
                    return pred

                pq.filters.append((f"moved to {stage} since {date_phrase.strip()}", make_pred()))
                pq.rank_hint = ("move_date", stage)
        working = working[: m.start()] + " " + working[m.end():]

    # --- 3. "reached <stage> but didn't get hired" --------------------------
    m = re.search(
        r"\breached\s+(?:the\s+)?([a-zA-Z]+)(?:\s+stage)?\s+but\s+"
        r"(?:didn'?t|did\s+not|never)\s+(?:get\s+)?hired\b",
        working, flags=re.IGNORECASE,
    )
    if m:
        pq.recognized_anything = True
        stage_word = m.group(1)
        stage, exact = best_stage_match(stage_word)
        if stage is None:
            pq.errors.append(
                f"'{stage_word}' isn't a stage in this pipeline. Valid stages are: "
                + ", ".join(STAGE_ORDER) + "."
            )
        else:
            if not exact:
                pq.notes.append(f"Reading '{stage_word}' as the '{stage}' stage.")

            def make_pred(stage=stage):
                def pred(c):
                    return c.reached(stage) and not c.is_hired
                return pred

            pq.filters.append((f"reached {stage} but not Hired", make_pred()))
        working = working[: m.start()] + " " + working[m.end():]

    # --- 4. exclude rejected -------------------------------------------------
    m = re.search(
        r"\b(?:except|excluding|without|minus)\s+(?:the\s+)?rejected(?:\s+candidates?)?\b"
        r"|\bnot\s+rejected\b|\bnon-?rejected\b",
        working, flags=re.IGNORECASE,
    )
    if m:
        pq.recognized_anything = True
        pq.filters.append(("excluding Rejected", lambda c: not c.is_rejected))
        working = working[: m.start()] + " " + working[m.end():]

    # --- 5. plain current-stage filter: "in <stage>" ------------------------
    # "in <word>" strongly signals stage intent in this domain, so if the
    # word cannot be resolved to a real stage we treat that as an error
    # rather than silently trying to match it as part of a name.
    m = re.search(r"\bin\s+(?:the\s+)?([a-zA-Z]{3,})(?:\s+stage)?\b", working, flags=re.IGNORECASE)
    if m:
        stage_word = m.group(1)
        stage, exact = best_stage_match(stage_word)
        if stage is not None:
            pq.recognized_anything = True
            if not exact:
                pq.notes.append(f"Reading '{stage_word}' as the '{stage}' stage.")
            pq.filters.append((f"currently in {stage}", lambda c, stage=stage: c.current_stage == stage))
            working = working[: m.start()] + " " + working[m.end():]
        elif stage_word.lower() not in _STOPWORDS:
            pq.recognized_anything = True
            pq.errors.append(
                f"'{stage_word}' isn't a stage in this pipeline. Valid stages are: "
                + ", ".join(STAGE_ORDER) + " (plus Rejected)."
            )
            working = working[: m.start()] + " " + working[m.end():]

    # --- 6. a bare, standalone stage name mentioned anywhere ("Interview") --
    if not pq.filters:
        m = re.search(r"\b(" + STAGE_PATTERN + r")\b", working, flags=re.IGNORECASE)
        if m:
            stage, _ = best_stage_match(m.group(1))
            if stage:
                pq.recognized_anything = True
                pq.filters.append((f"currently in {stage}", lambda c, stage=stage: c.current_stage == stage))
                working = working[: m.start()] + " " + working[m.end():]

    # --- whatever is left is treated as a name fragment ---------------------
    leftover_tokens = [t for t in re.split(r"[^a-zA-Z']+", working) if t]
    name_tokens = [t for t in leftover_tokens if t.lower() not in _STOPWORDS]
    pq.name_fragment = " ".join(name_tokens).strip()

    return pq


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class SearchResult:
    def __init__(self, candidates, explanation, notes, errors, understood, used_ai=False):
        self.candidates = candidates      # list of (CandidateView, score)
        self.explanation = explanation
        self.notes = notes
        self.errors = errors
        self.understood = understood
        self.used_ai = used_ai


def _execute(all_candidates, pq, query_text, used_ai=False):
    """Shared by both the regex parser and the AI parser: apply pq's
    filters, rank, and build an explanation. Both paths produce the same
    ParsedQuery shape, so everything from here down is identical."""
    if pq.errors:
        return SearchResult([], None, pq.notes, pq.errors, False, used_ai)

    if not pq.recognized_anything and not pq.name_fragment:
        return SearchResult(
            [], None, [],
            [
                f"I couldn't understand '{query_text}'. Try things like: "
                "\"Priya Sharma\", \"who's in Interview\", "
                "\"stuck in Screening for more than a week\", "
                "\"moved to Interview since Monday\", "
                "\"reached Offer but didn't get hired\", or "
                "\"everyone except rejected candidates\"."
            ],
            False, used_ai,
        )

    # Apply all AND-ed filters.
    candidates = all_candidates
    for _desc, pred in pq.filters:
        candidates = [c for c in candidates if pred(c)]

    # `scored` holds (candidate, display_score) where display_score is a
    # 0-1 name-similarity value shown to the recruiter, or None when ranking
    # was instead driven by a filter (duration/date) rather than name match.
    scored = []
    if pq.name_fragment:
        for c in candidates:
            sim = _name_similarity(pq.name_fragment, c.name)
            if sim >= NAME_MATCH_THRESHOLD:
                scored.append((c, sim))
        scored.sort(key=lambda pair: (-pair[1], pair[0].name.lower()))
    else:
        # No name to match on -- rank by whatever makes sense for the filter,
        # but only expose a name-similarity-style score when we have one.
        if pq.rank_hint and pq.rank_hint[0] == "stage_duration":
            ordered = sorted(candidates, key=lambda c: -c.time_in_current_stage().total_seconds())
        elif pq.rank_hint and pq.rank_hint[0] == "move_date":
            stage = pq.rank_hint[1]
            ordered = sorted(candidates, key=lambda c: c.reached_at.get(stage, ""), reverse=True)
        else:
            ordered = sorted(candidates, key=lambda c: c.name.lower())
        scored = [(c, None) for c in ordered]

    # Build a human explanation of what we understood.
    parts = []
    if pq.name_fragment:
        parts.append(f"name matches '{pq.name_fragment}'")
    parts.extend(desc for desc, _ in pq.filters)
    explanation = "Matching: " + "; ".join(parts) + "." if parts else None

    if not scored:
        no_match_reason = (
            "No candidates match " + (", ".join(parts) if parts else "that query") + "."
        )
        return SearchResult([], None, pq.notes, [no_match_reason], True, used_ai)

    return SearchResult(scored, explanation, pq.notes, [], True, used_ai)


def search(all_candidates, query_text):
    """The original, dependency-free regex + fuzzy-match parser."""
    query_text = (query_text or "").strip()

    if not query_text:
        ranked = [(c, 0.0) for c in sorted(all_candidates, key=lambda c: c.name.lower())]
        return SearchResult(ranked, "Showing every candidate.", [], [], True)

    pq = parse_query(query_text)
    return _execute(all_candidates, pq, query_text)


def _parsed_query_from_ai(data):
    """Convert the AI's structured JSON into the same ParsedQuery shape
    parse_query() produces, re-validating every stage name it gives us
    (never trust it blindly -- the model can still get this wrong)."""
    pq = ParsedQuery()

    def resolve(stage_word, field_label):
        if not stage_word:
            return None
        stage, exact = best_stage_match(stage_word)
        if stage is None:
            pq.errors.append(
                f"'{stage_word}' isn't a stage in this pipeline. Valid stages are: "
                + ", ".join(STAGE_ORDER) + " (plus Rejected)."
            )
            return None
        if not exact:
            pq.notes.append(f"Reading '{stage_word}' ({field_label}) as the '{stage}' stage.")
        return stage

    if data.get("clarification_needed"):
        pq.errors.append(data["clarification_needed"])
        return pq

    name_fragment = (data.get("name_fragment") or "").strip()
    if name_fragment:
        pq.name_fragment = name_fragment
        pq.recognized_anything = True

    current_stage = resolve(data.get("current_stage"), "current stage")
    if current_stage:
        pq.filters.append((f"currently in {current_stage}",
                            lambda c, s=current_stage: c.current_stage == s))
        pq.recognized_anything = True

    stuck_stage = resolve(data.get("stuck_stage"), "stuck stage")
    stuck_days = data.get("stuck_min_days")
    if stuck_stage and stuck_days is not None:
        def make_stuck(s=stuck_stage, d=stuck_days):
            return lambda c: c.current_stage == s and c.time_in_current_stage().total_seconds() / 86400 >= d
        pq.filters.append((f"stuck in {stuck_stage} for {stuck_days}+ day(s)", make_stuck()))
        pq.rank_hint = ("stage_duration", stuck_stage)
        pq.recognized_anything = True

    moved_stage = resolve(data.get("moved_stage"), "moved-to stage")
    moved_since = data.get("moved_since_date")
    if moved_stage and moved_since:
        since_dt = parse_date_phrase(moved_since)
        if since_dt is None:
            pq.errors.append(f"I couldn't understand the date '{moved_since}'.")
        else:
            def make_moved(s=moved_stage, since_dt=since_dt):
                def pred(c):
                    at = c.reached_at.get(s)
                    return at is not None and parse_iso(at) >= since_dt
                return pred
            pq.filters.append((f"moved to {moved_stage} since {moved_since}", make_moved()))
            pq.rank_hint = ("move_date", moved_stage)
            pq.recognized_anything = True

    reached_stage = resolve(data.get("reached_stage_not_hired"), "reached-stage")
    if reached_stage:
        pq.filters.append((f"reached {reached_stage} but not Hired",
                            lambda c, s=reached_stage: c.reached(s) and not c.is_hired))
        pq.recognized_anything = True

    if data.get("exclude_rejected"):
        pq.filters.append(("excluding Rejected", lambda c: not c.is_rejected))
        pq.recognized_anything = True

    return pq


def search_ai(all_candidates, query_text, api_key=None):
    """AI-assisted parsing. Raises ai_search.AIQueryError if the AI can't
    be reached or misbehaves -- callers should catch that and fall back
    to search() (see smart_search below, or app.py's /api/search route)."""
    from . import ai_search  # local import: keeps the AI dependency optional

    query_text = (query_text or "").strip()
    if not query_text:
        ranked = [(c, 0.0) for c in sorted(all_candidates, key=lambda c: c.name.lower())]
        return SearchResult(ranked, "Showing every candidate.", [], [], True, used_ai=False)

    data = ai_search.interpret_query(query_text, api_key=api_key)
    pq = _parsed_query_from_ai(data)
    return _execute(all_candidates, pq, query_text, used_ai=True)


def smart_search(all_candidates, query_text, use_ai=False, api_key=None):
    """Convenience wrapper: try AI parsing when requested, silently fall
    back to the regex parser on any failure so search never just breaks."""
    if not use_ai:
        return search(all_candidates, query_text)

    from . import ai_search

    try:
        return search_ai(all_candidates, query_text, api_key=api_key)
    except ai_search.AIQueryError as e:
        result = search(all_candidates, query_text)
        fallback_note = f"(AI search unavailable: {e} Falling back to standard search.)"
        result.notes = [fallback_note] + result.notes
        return result
