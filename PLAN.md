# PLAN.md — Orbit Air Baggage Desk

## 1. The problem (in my own words)

Orbit Air's baggage desk deals with three kinds of claims: **delayed**, **lost**, and **damaged** bags. Right now there's no single place to file a claim, see who is working on it, or notice when one has sat too long.

I'm building a command-line tool (CLI) for desk staff that lets them:

- **file** a claim for a passenger on a flight, choosing its type and the passenger's tier;
- **assign** a claim to an agent;
- **move** a claim through its statuses, with every change saved to a **history** table so we can see who changed what and when;
- **work out each claim's deadline** from its tier, and **escalate** claims that are past their deadline and still haven't been dealt with.

The data lives in a database with two tables, `claims` and `history`. The rule code never reads the real clock. The current time is always passed in as `now`, so the tests can control it exactly.

## 2. Rules (in my own words)



### Deadlines

The deadline is counted from the moment the claim is filed (`filed_at`), and how long we get depends on the passenger's tier:


| Tier     | Hours from `filed_at` |
| -------- | --------------------- |
| gold     | 4                     |
| silver   | 24                    |
| standard | 72                    |


- When a claim is filed, I work out `deadline = filed_at + tier hours` and store it on the claim.
- A claim is **overdue only when** `now` **is later than the deadline**. If `now` is exactly the deadline, it is *not* overdue.
- `now` is always passed in. The rule code never calls the real clock.



### Allowed status changes

There are five statuses: `open`, `assigned`, `escalated`, `resolved`, `closed`.


| From        | Allowed to go to        |
| ----------- | ----------------------- |
| `open`      | `assigned`, `escalated` |
| `assigned`  | `resolved`, `escalated` |
| `escalated` | `assigned`, `resolved`  |
| `resolved`  | `closed`                |
| `closed`    | nothing (final)         |


- Anything not in this table is refused, and the claim and history are left unchanged.
- **Escalation rule:** a claim can only be escalated if its status is `open` or `assigned` **and** it is overdue at the given `now`. Trying to escalate a claim that isn't overdue, or that's in any other status, is refused.
- Every status change that succeeds adds one row to `history`.



## 3. Tables and columns



### `claims`


| Column       | Type          | Notes                                                                                   |
| ------------ | ------------- | --------------------------------------------------------------------------------------- |
| `id`         | INTEGER PK    |                                                                                         |
| `passenger`  | TEXT NOT NULL | `CHECK (trim(passenger) <> '')`, blank names rejected                                   |
| `flight`     | TEXT NOT NULL | `CHECK (trim(flight) <> '')`, e.g. `OA123`                                              |
| `claim_type` | TEXT NOT NULL | `CHECK (claim_type IN ('delayed','lost','damaged'))`                                    |
| `tier`       | TEXT NOT NULL | `CHECK (tier IN ('gold','silver','standard'))`                                          |
| `status`     | TEXT NOT NULL | `CHECK (status IN ('open','assigned','escalated','resolved','closed'))`, default `open` |
| `agent`      | TEXT          | NULL until the claim is assigned                                                        |
| `note`       | TEXT          | free text, optional                                                                     |
| `filed_at`   | TEXT NOT NULL | ISO-8601 timestamp                                                                      |
| `deadline`   | TEXT NOT NULL | `filed_at` + tier hours, set when filed                                                 |




### `history`


| Column       | Type                               | Notes                                         |
| ------------ | ---------------------------------- | --------------------------------------------- |
| `id`         | INTEGER PK                         |                                               |
| `claim_id`   | INTEGER NOT NULL, FK → `claims.id` |                                               |
| `old_status` | TEXT                               | NULL for the first "filed" row                |
| `new_status` | TEXT NOT NULL                      |                                               |
| `changed_by` | TEXT NOT NULL                      | the agent or staff member who made the change |
| `changed_at` | TEXT NOT NULL                      | the `now` passed in                           |




## 4. Git branches and planned tests

I'll do the work on four feature branches, in this order, and merge each one only when its tests pass. Nothing is done directly on `main`.


| #   | Branch                             | Min. tests | What it adds                                               |
| --- | ---------------------------------- | ---------- | ---------------------------------------------------------- |
| 1   | `feature/schema-and-filing`        | 5          | create both tables; file a claim; list claims with filters |
| 2   | `feature/assign-and-status`        | 6          | assign to an agent; status changes; history                |
| 3   | `feature/deadlines-and-escalation` | 6          | deadline math; overdue check; escalation; rollback         |
| 4   | `feature/cli`                      | 3          | CLI commands, `seed`, and the `--now` option               |




### 1. `feature/schema-and-filing`

1. Creating the schema makes both `claims` and `history` tables.
2. Filing a valid claim saves it with status `open`, no agent, the correct `deadline`, and a first `history` row.
3. Filing a claim with a blank passenger (`''` or only spaces) is rejected.
4. Filing a claim with a blank flight (`''` or only spaces) is rejected.
5. Filing a claim with an invalid `claim_type` or `tier` is rejected (CHECK constraint).
6. Listing claims with filters (e.g. by status, tier, or claim type) returns only the matching claims.



### 2. `feature/assign-and-status`

1. Assigning an `open` claim sets `agent` and moves it to `assigned`.
2. Every allowed status change in the table succeeds.
3. Disallowed: `open → closed` is refused.
4. Disallowed: `resolved → assigned` is refused.
5. Disallowed: `closed → open` (or any change out of `closed`) is refused.
6. Each successful change adds a `history` row with the right `old_status`, `new_status`, `changed_by`, `changed_at`, and a refused change leaves the claim and history unchanged.



### 3. `feature/deadlines-and-escalation`

1. Deadline is filed_at + 4 / 24 / 72 hours for gold / silver / standard.
2. **One minute before** the deadline: not overdue.
3. **Exactly at** the deadline: not overdue.
4. **One minute after** the deadline: overdue.
5. Escalating at `now` changes only the overdue `open`/`assigned` claims and returns their ids. Claims that aren't overdue, or are `escalated`/`resolved`/`closed`, stay as they were.
6. **Rollback:** a test forces the history insert to fail on purpose during a status change, then checks that the claim's status did not change and no history row was added.



### 4. `feature/cli`

1. `seed seed_claims.csv` loads the claims from the CSV into the database.
2. `--now` drives escalation: running the escalate command with a given `--now` escalates exactly the claims overdue at that time and prints their ids.
3. Bad input (unknown command, invalid tier/type, blank passenger) exits with an error message and a non-zero exit code.



## 5. Risks and how I'll handle them

1. **Getting the deadline boundary wrong.** Using `>=` instead of `>` would mark a claim overdue exactly on its deadline.
  *How I'll handle it:* use `now > deadline` in a single helper function, and test one minute before, exactly at, and one minute after.
2. **Accidentally reading the real clock.** A stray `datetime.now()` would make the tests flaky and break the project rule.
  *How I'll handle it:* every function that needs the time takes `now` as a parameter. Tests pass fixed datetimes, and before each merge I'll search the source for `datetime.now`, `utcnow`, and `time.time`.
3. **Status and history getting out of sync.** If the status update works but the history insert fails (or the other way around), the record is wrong.
  *How I'll handle it:* do the status update and the history insert in one database transaction. A test forces the history write to fail and checks that the status rolled back.
4. **Invalid data getting into the database.** For example, a typo in a tier
  or claim type.
   *How I'll handle it:* CHECK constraints on `claim_type`, `tier`, and `status`, a foreign key on `history.claim_id` (with foreign keys switched on), and tests that try to insert bad values.

