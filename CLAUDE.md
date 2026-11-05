# CLAUDE.md

## Commands
- Activate the virtual environment: `source .venv/bin/activate`
- Run all tests: `pytest`
- Run one test file: `pytest tests/test_claims.py`
- Lint: `ruff check .`

## Deadline hours by tier (counted from the filed time)
- gold: 4 hours
- silver: 24 hours
- standard: 72 hours
- A claim is overdue only when now is later than the deadline. Exactly at the deadline is not overdue.

## Rules
- The tests are the spec. Do not edit anything in `tests/` unless I explicitly ask.
- Never read the real clock in rule code. The current time is always passed in as `now`.
- Never read, print, or commit `.env`.
- Work on the feature branch named in the task, never directly on `main`.

