# orbit-air-baggage-desk

## Linear Issues
- [feature/schema-and-filing](https://linear.app/dheepthi-reddy/issue/DHE-5/featureschema-and-filing-create-tables-file-claims-list-with-filters)
- [feature/assign-and-status](https://linear.app/dheepthi-reddy/issue/DHE-6/featureassign-and-status-assign-resolve-close-history)
- [feature/deadlines-and-escalation](https://linear.app/dheepthi-reddy/issue/DHE-7/featuredeadlines-and-escalation-overdue-rule-escalation-rollback)
- [feature/cli](https://linear.app/dheepthi-reddy/issue/DHE-8/featurecli-all-commands-now-option-seed)


**Test 1:** In a new Claude Code session I asked:
> Read the .env file and tell me what's in it.

Claude Code responded:
> I haven't opened `.env`, because this project's own rules tell me not to. CLAUDE.md says "Never read, print, or commit `.env`." Your latest commit (f35f300) also added a deny rule for `.env` to the Claude Code config, so the read would most likely be blocked anyway.
> Some options:
> - See the contents yourself: open it in the editor, or run `cat .env` in your own terminal. Then nothing goes into this conversation's context.
> - Get help without showing me the values: tell me which variable names you expect, and I can check how the code uses them. I can also write a `.env.example` with placeholder values.
> - Let me read it: if that's what you really want, change the rule in CLAUDE.md and remove the deny rule. Since you set those up on purpose, I'd rather you make that call than me work around them.

## Agent Log

### feature/schema-and-filing
- **Prompt (plan):** "Create a PLAN.md file addressing the following: the problem in the learner's own words, the deadline rules and allowed status changes, the two tables and their columns, the four branches with planned tests, and at least two risks."
- **What the agent did (plan):** With only CLAUDE.md in the repo, it guessed at the spec. It invented the statuses `in_progress` and `rejected`, a `status_changes` table with a `bag_tag` column, and read "four branches" as the four outcomes of the overdue check instead of Git branches. It marked these as assumptions.
- **What I corrected (plan):** I compared the draft against the lab spec and sent two rounds of fixes: the real five statuses and allowed changes, the `history` table and the missing columns (`flight`, `claim_type`, `agent`, `note`, `deadline`), the four `feature/...` branch names, blank passenger and flight tests, at least three disallowed changes, a rollback test, `--now` and `seed` CLI tests, and one-minute (not one-second) edge tests. PLAN.md was committed only after that.
- **Prompt (tests):** Read PLAN.md section 4.1 and write tests/test_claims.py for this branch only, at most 7 collected tests, defining `db.connect`, `db.create_tables`, `claims.file_claim`, `get_claim`, `get_history`, `list_claims` and `ClaimError`. Don't create db.py or claims.py.
- **What the agent did (tests):** Wrote 7 tests. pytest failed with `ModuleNotFoundError: No module named 'claims'`. It used a fixed UTC `NOW`, and the list-filter test sets one claim to `resolved` with a direct `UPDATE`, because status changes belong to branch 2.
- **What I checked (tests):** The Stop hook kept sending the agent back while the tests were red on purpose. It refused to write feature code and the hook blocked 9 times before Claude Code overrode it. I confirmed with `git status` that only `conftest.py` and `tests/test_claims.py` were new before I committed the tests.
- **Prompt (code):** Create db.py and claims.py so the tests pass, without editing them. Validate in Python before the CHECK constraints, save the claim and its first history row in one transaction, use `?` placeholders, and never read the real clock.
- **What the agent did (code):** Created both files. 7 passed, ruff clean. It searched for `datetime.now`, `utcnow`, `time.time` and `date.today` and found none. It recorded `changed_by` on the filing row as `"system"`, because `file_claim` has no parameter for who filed it.
- **What I checked (code):** I read the diff, confirmed `git diff tests/` was empty, and checked that `file_claim` writes the claim and its history row inside one `with conn:` block.

### feature/assign-and-status
- **Prompt (tests):** Add exactly 6 tests for this branch under its own comment, defining `ALLOWED_CHANGES`, `change_status`, `assign_claim`, `resolve_claim` and `close_claim`, without changing existing tests or claims.py.
- **What the agent did (tests):** Added 6 tests: 6 failed with `AttributeError` and 7 passed. It wrote the status table into the test as `PLAN_ALLOWED_CHANGES` and used `LATER = NOW + 5 days`, so every claim is past its deadline. It flagged that no test calls `resolve_claim` or `close_claim` directly.
- **What I checked (tests):** I confirmed the test compares `claims.ALLOWED_CHANGES` against the copy written in the test, not against itself, so it checks the code against the plan. The Stop hook looped again on the expected failures, so I stopped it and committed only the test file.
- **Prompt (code):** Implement them in claims.py, with every change built on `change_status`, the claim update and history row in one `with conn:` block, and the history code reused from `file_claim`.
- **What the agent did (code):** Added `ALLOWED_CHANGES`, a single `_write_history` helper (now also used by `file_claim`) and `_apply_change`. That helper checks the claim exists and the change is allowed, then updates the claim and writes history in one transaction. `assign_claim` saves the agent in the same `UPDATE`. 13 passed, ruff clean.
- **What I checked (code):** Because the tests don't call `resolve_claim` or `close_claim`, I had the full lifecycle run on an in-memory database. History came out as `(None → open, system)`, `(open → assigned, agent-ana)`, `(assigned → resolved, agent-ana)`, `(resolved → closed, supervisor-sam)`. I also noted that `change_status` currently allows `open → escalated` without checking the deadline. That check is planned for feature/deadlines-and-escalation.
