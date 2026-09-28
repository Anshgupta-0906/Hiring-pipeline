# The Docket - a mini hiring pipeline

A small Flask + SQLite web app for running one job requisition through
**Applied -> Screening -> Interview -> Offer -> Hired**, with a single
plain-English search box (and optional AI-assisted search).

- [How to run](#how-to-run)
- [Decisions and why](#decisions-and-why)
- [What I'd do with more time](#what-id-do-with-more-time)
- [How I used AI (and where I disagreed with it)](#how-i-used-ai-and-where-i-disagreed-with-it)
- [Reference: search, API, layout](#reference)

## What it does

- Add candidates and see everyone grouped by stage on a board.
- Move candidates one stage at a time. Skipping stages, or reversing a final
  outcome (Hired / Rejected), is refused by the server (HTTP 409).
- Open a candidate to see their full history and time in the current stage.
  History is append-only: the app never updates or deletes an event.
- One search box: fuzzy names ("sharam" finds Priya Sharma), current stage,
  "stuck in Screening for more than a week", "moved to Interview since
  Monday", "reached Offer but didn't get hired", "everyone except rejected",
  and combinations. Results are ranked, and queries that make no sense get
  an explanation instead of an empty list.

## How to run

Requirements: Python 3.6+ (3.8+ recommended). Flask is the only dependency.

```bash
# 1. Get the code
git clone <YOUR_REPO_URL>
cd <repo-folder>

# 2. (Recommended) virtual environment
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate

# 3. Install
pip install -r requirements.txt

# 4. (Optional) load 7 sample candidates. WARNING: this wipes the database.
python3 seed.py

# 5. Start
python3 app.py
```

Open **http://localhost:5000**. Stop with Ctrl+C. Data lives in `pipeline.db`
(created on first run, git-ignored) and survives restarts. Run only one
instance of the server at a time.

### Optional: AI-assisted search

The default search is a local parser: no key, no internet, no cost. To let
Claude interpret looser phrasings, set a key before starting the server:

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # PowerShell: $env:ANTHROPIC_API_KEY="..."
python3 app.py
```

An "Ask AI to interpret this query" checkbox then appears under the search
box (hidden otherwise). The key is read from the environment only; it is
never stored. Any AI failure falls back to the local parser with a visible note.

## Decisions and why

**Current stage is derived, never stored.** A candidate's stage is the
`to_stage` of their latest event. There is no `current_stage` column that
could drift out of sync with the history, so the audit trail and the board
cannot disagree.

**The history is insert-only by construction.** The application code only
ever INSERTs into `events`, and no API route edits or deletes one. "Reached
Offer but was never hired" is answerable precisely because rejected
candidates keep their whole past.

**Rules live on the server** (`pipeline/stages.py`), not in the UI. Buttons
are hidden when a move is illegal, but the API independently refuses it, so
the rules hold for any client.

**Rejected is a separate tray, not a sixth column.** Rejection can happen
from any stage, so it isn't a step in the flow. The board shows the live
pipeline; rejected people are one click away and appear when a search hits them.

**SQLite.** Zero setup, durable across restarts, and easy to inspect. The
trade-off is weak concurrent writes, acceptable for one recruiter.

**A hand-rolled search parser instead of an NLP library.** The question
vocabulary in the brief is small and closed. A handful of regex clauses plus
`difflib` fuzzy matching is predictable, testable, and free. Recognised
clauses become filters that are AND-ed; leftover words become a name
fragment. Stage names are fuzzy-matched too, but with a stricter threshold
than names, because loose matching turned ordinary words like "pipeline"
into the stage "Applied".

**Search always explains itself.** Unknown stage, unparseable date, or text
that matches nobody returns a reason and example queries. "No results" and
"I didn't understand you" are reported differently.

**AI search only interprets; it never queries.** I chose not to let the
model write SQL. It returns a small structured filter; Python re-validates
every stage name and runs it through the same execution code as the local
parser. This keeps results deterministic and means a bad model output can
at worst pick a wrong filter, never run an arbitrary query. It is opt-in per
search, so cost and latency are the user's choice.

## What I'd do with more time

Most important first:

1. **Automated tests.** There are none; everything was checked by hand and
   with curl. I'd cover the transition rules, each search clause and its
   combinations, and the fuzzy-match thresholds.

2. **Enforce immutability in the database.** Anyone with `pipeline.db` can
   edit it and `seed.py` itself updates timestamps to fake old data. I'd
   add SQLite triggers that reject UPDATE/DELETE on `events`, and give the
   seed script a supported way to insert backdated events.

3. **Make transitions atomic.** Advance/reject reads the current stage, then
   writes in a separate step. Two simultaneous requests could both pass
   validation. One transaction (with a check against the latest event) fixes it.

4. **Time zones.** "Since Monday" and "days in stage" use UTC. A recruiter's
   Monday should be in her local zone.

5. **Better search.** OR queries, saved searches, and more phrasings. Today a
   query like "who is in the pipeline" wrongly reports "'pipeline' isn't a
   stage", because any "in <word>" is treated as a stage attempt.

6. **Correction entries.** A way to fix a mistake (e.g. advanced the wrong
   person) by appending a correction event, plus renaming candidates.

7. **Test the AI path live.** I verified the request plumbing and error
   handling (a bad key returns a clean 401 and falls back) and unit-tested the
   JSON-to-filter conversion with mocked responses, but never ran a query
   through the model with a real key.

8. **Auth and deployment.** No login today; it's a local single-user app. A
   production setup would use a real WSGI server and a proper database.

## How I used AI (and where I disagreed with it)

I used AI as a development assistant throughout the project for design decisions, debugging, and implementing the natural-language search functionality. I used its suggestions as a starting point, then integrated and modified them based on the requirements of the application.

For the search functionality, AI initially suggested an event-log data model with a regex-based clause parser and difflib fuzzy matching. I implemented this approach, including error handling for unsupported queries. However, I identified limitations such as AND-only filters and the need to add a new regex pattern for every new type of question.

I therefore disagreed with the initial approach as the complete solution and decided to add an AI-assisted layer to the search box. The AI interprets the user's natural-language query and converts it into a structured format, while the existing Python search logic performs validation, filtering, and database access. I also retained the original regex + fuzzy-matching implementation as a fallback when AI is unavailable.

I also used AI to help diagnose and fix a Python compatibility issue involving datetime.fromisoformat, resulting in a custom ISO timestamp parser.

For the AI-assisted search implementation, I tested the API request plumbing and fallback behavior using a fake API key and unit-tested the JSON-to-filter conversion with mocked responses. Due to the limited assessment time and lack of a working API key, I could not perform an end-to-end test of real AI query interpretation.

Overall, I used AI for brainstorming, debugging, and implementation assistance, but made the final architectural decisions myself and retained deterministic application-side logic for database access and fallback behavior.

### Search examples

| Type | Finds |
|---|---|
| `sharam` | Priya Sharma (typo-tolerant) |
| `who's in interview` | everyone currently in Interview |
| `stuck in screening for more than a week` | 7+ days in Screening |
| `moved to interview since monday` | entered Interview on/after Monday |
| `reached offer but didn't get hired` | ever reached Offer, not Hired |
| `everyone except rejected candidates` | all non-rejected |
| `priya in interview` | filters combine with AND (no OR yet) |

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/candidates` | all candidates grouped by stage |
| POST | `/api/candidates` | add a candidate `{"name": "..."}` |
| GET | `/api/candidates/<id>` | one candidate with full history |
| POST | `/api/candidates/<id>/advance` | move one stage forward |
| POST | `/api/candidates/<id>/reject` | reject (refused after Hired) |
| GET | `/api/search?q=...&ai=1` | search (`ai=1` optional) |
| GET | `/api/ai-status` | is AI search configured? |

### Layout

```
app.py                Flask app + routes
seed.py               sample data (wipes the DB)
requirements.txt
pipeline/
  stages.py           transition rules
  model.py            CandidateView built from events
  search.py           parser, fuzzy match, ranking, explanations
  ai_search.py        optional Claude query interpretation
  db.py               SQLite, insert-only events
  timeutil.py         Python 3.6-compatible timestamp helpers
templates/index.html
static/               app.js, style.css
docs/AI_CHAT_LOG.md   the AI conversation
```
