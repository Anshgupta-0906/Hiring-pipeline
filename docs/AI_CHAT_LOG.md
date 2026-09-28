# AI chat log

> **Note:** This AI chat log contains only the relevant AI interactions that contributed to the development of the project. I have not included every conversation or minor interaction with AI. The entries below highlight the important design decisions, debugging assistance, implementation guidance, and the points where I modified or disagreed with the AI's suggestions.

### 1. Help with search functionality
**User:** I am building a Mini Hiring Pipeline web application where recruiters can manage candidates through the stages Applied → Screening → Interview → Offer → Hired, with Rejected possible before Hired.

The application needs a single natural-language search box that can understand queries such as:
- "Find Priya Sharma"
- "Who's in Interview right now?"
- "Who has been stuck in Screening for more than a week?"
- "Who moved to Interview since Monday?"
- "Who reached Offer stage but didn't get hired?"
- "Everyone except rejected candidates"

Give me ideas to implement this search functionality

**AI:** The event-log data model, plus a regex clause parser combined with difflib fuzzy matching, and honest error messages.

**What I Implemented:** I implemented the event-log data model, plus a regex clause parser combined with difflib fuzzy matching, and honest error messages.

The trade-offs I accepted:

Filters combine with AND only, with no OR.
Phrasings outside the patterns fall through to the name search.
Every new question type needs a new pattern.

### 2. Bug: adding a candidate fails
**User:** AttributeError: type object 'datetime.datetime' has no attribute 'fromisoformat'

**AI:** Recognised the cause: Python older than 3.7 lacks
`datetime.fromisoformat`.

**What I Implemented:** Added `pipeline/timeutil.py` with a hand-written
ISO parser and replaced every use.

### 3. AI-assisted search
**User:** How can we integrate AI to the project's search box so that it could
understand what we are asking and access the database to give the correct result

**AI:** Pushed back on the literal ask: rather than letting the model write and
run SQL, it proposed having the model return a structured filter that Python
validates and executes with the existing code. 

**What I Implemented:** Built `ai_search.py`, a shared
`_execute()` used by both parsers, a `smart_search()` fallback, an
`/api/ai-status` endpoint and an opt-in checkbox. Tested request plumbing
against the real API with a fake key (clean 401 -> fallback) and unit-tested
the JSON-to-filter conversion with mocked responses. I had no time to test a real interpretation using a working key.
