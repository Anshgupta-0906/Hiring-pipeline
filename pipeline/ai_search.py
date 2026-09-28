"""
Optional AI-assisted query understanding for the search box.

Design intent: the model NEVER touches the database directly and never
generates SQL. It only reads the recruiter's free-text query and returns a
small structured JSON object describing which of the app's existing,
fixed filter types apply (current stage, "stuck for N days", "moved since
<date>", "reached X but not hired", name fragment, exclude-rejected).
Python then applies that structured filter to already-loaded candidate
data using the exact same predicate functions the regex parser uses.

This keeps behavior predictable and safe -- a crafted or ambiguous query
can, at worst, make the AI ask for one of these filters incorrectly. It
can never run an arbitrary query, and it never sees more of the database
than the candidate list it's asked to filter.

If ANTHROPIC_API_KEY isn't set, or the API call fails for any reason,
callers should catch AIQueryError and fall back to the regular parser --
see search.py's `search()` function.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

from .stages import STAGE_ORDER

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Small, fast, cheap model -- this is a lightweight classification/
# extraction task, not open-ended generation.
MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """You turn a recruiter's free-text search query into a structured JSON filter for a candidate-tracking tool. You do not answer the query yourself and you never write SQL -- you only decide which of a FIXED set of filters apply, so a separate program can run them safely.

Pipeline stages, in order: Applied, Screening, Interview, Offer, Hired. A candidate can also be Rejected (a terminal state, not part of the forward order).

Today's date is {today}.

Return ONLY a single JSON object (no markdown fences, no commentary) with exactly these keys:

{{
  "name_fragment": string or null,       // a person's name or partial name to fuzzy-match, e.g. "priya" or "sharma"
  "current_stage": string or null,       // one of the stage names above -- candidate must currently be in this stage
  "stuck_stage": string or null,          // one of the stage names -- paired with stuck_min_days
  "stuck_min_days": number or null,       // minimum days in stuck_stage (e.g. "more than a week" -> 7)
  "moved_stage": string or null,          // one of the stage names -- paired with moved_since_date
  "moved_since_date": string or null,     // ISO date YYYY-MM-DD that the candidate must have MOVED INTO moved_stage on or after -- resolve relative dates ("Monday", "yesterday", "last week") yourself using today's date above
  "reached_stage_not_hired": string or null, // one of the stage names -- candidate reached this stage at some point but current stage is not Hired
  "exclude_rejected": true or false,      // true if the query asks to exclude/omit rejected candidates
  "clarification_needed": string or null // if the query asks for something this fixed filter set cannot express (e.g. counting, comparing two named people, arbitrary stats, or is just gibberish), explain briefly why in one sentence here and leave the other fields null/false
}}

Rules:
- Only ever use the five stage names listed (Rejected only for exclude_rejected/current_stage, not for stuck/reached/moved fields since it's not a forward stage... actually current_stage MAY be "Rejected" if the recruiter asks "who's in Rejected", but stuck_stage/moved_stage/reached_stage_not_hired must be one of Applied, Screening, Interview, Offer, Hired only).
- If the recruiter names a stage that doesn't exist in this pipeline (e.g. "Onboarding"), set clarification_needed explaining that stage doesn't exist and name the valid stages, and leave other fields null.
- Multiple filters can and should be combined when the query implies it (e.g. "priya in interview" -> name_fragment "priya" AND current_stage "Interview").
- Be forgiving of typos in both names and stage names.
- If the query is empty, vague, or just "everyone"/"all", return all fields null/false (no filter -- matches everyone).
- Never invent a name_fragment from words that are clearly describing a filter (like "interview", "rejected", "week") -- only real apparent name text belongs there.
"""


class AIQueryError(Exception):
    """Raised whenever AI-assisted parsing can't be used -- missing key,
    network failure, bad response shape, etc. Callers should catch this
    and fall back to the regex parser."""
    pass


def _call_anthropic(query_text, api_key):
    system = _SYSTEM_PROMPT.format(today=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    payload = {
        "model": MODEL,
        "max_tokens": 400,
        "system": system,
        "messages": [{"role": "user", "content": query_text}],
    }
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise AIQueryError(f"Anthropic API returned {e.code}: {detail[:200]}")
    except urllib.error.URLError as e:
        raise AIQueryError(f"Could not reach the Anthropic API: {e.reason}")
    except TimeoutError:
        raise AIQueryError("The Anthropic API request timed out.")

    try:
        text = "".join(
            block["text"] for block in body["content"] if block.get("type") == "text"
        )
    except (KeyError, TypeError):
        raise AIQueryError("Unexpected response shape from the Anthropic API.")

    return text


def interpret_query(query_text, api_key=None):
    """Ask Claude to turn `query_text` into a structured filter dict.
    Raises AIQueryError on any failure -- callers should catch this and
    fall back to the regex-based parser."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIQueryError("No ANTHROPIC_API_KEY configured.")

    raw_text = _call_anthropic(query_text, api_key)

    # Be tolerant of the model wrapping the JSON in a code fence anyway.
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        raise AIQueryError("The AI's response wasn't valid JSON.")

    expected_keys = {
        "name_fragment", "current_stage", "stuck_stage", "stuck_min_days",
        "moved_stage", "moved_since_date", "reached_stage_not_hired",
        "exclude_rejected", "clarification_needed",
    }
    if not expected_keys.issubset(data.keys()):
        raise AIQueryError("The AI's response was missing expected fields.")

    return data
