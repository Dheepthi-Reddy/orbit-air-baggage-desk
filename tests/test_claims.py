"""Tests for branch feature/schema-and-filing (PLAN.md section 4.1)."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

import claims
import db

# Fixed "current time". The tests never read the real clock.
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def as_datetime(value):
    """Accept a stored ISO-8601 string or a datetime and return a datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def row_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_create_tables_makes_claims_and_history(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    names = {row[0] for row in rows}

    assert {"claims", "history"} <= names


def test_file_valid_gold_claim_saves_open_claim_and_history(conn):
    claim_id = claims.file_claim(
        conn, "Ada Lovelace", "OA123", "lost", "gold", NOW, note="Blue suitcase"
    )

    claim = claims.get_claim(conn, claim_id)
    assert claim["passenger"] == "Ada Lovelace"
    assert claim["flight"] == "OA123"
    assert claim["claim_type"] == "lost"
    assert claim["tier"] == "gold"
    assert claim["note"] == "Blue suitcase"
    assert claim["status"] == "open"
    assert claim["agent"] is None
    assert as_datetime(claim["filed_at"]) == NOW
    assert as_datetime(claim["deadline"]) == NOW + timedelta(hours=4)

    history = claims.get_history(conn, claim_id)
    assert len(history) == 1
    assert history[0]["old_status"] is None
    assert history[0]["new_status"] == "open"
    assert as_datetime(history[0]["changed_at"]) == NOW


@pytest.mark.parametrize(
    ("passenger", "flight", "claim_type", "tier", "message"),
    [
        pytest.param("   ", "OA123", "lost", "gold", r"passenger", id="blank-passenger"),
        pytest.param("Ada Lovelace", "", "lost", "gold", r"flight", id="blank-flight"),
        pytest.param(
            "Ada Lovelace", "OA123", "stolen", "gold", r"claim_type|stolen",
            id="unknown-claim-type",
        ),
        pytest.param(
            "Ada Lovelace", "OA123", "lost", "platinum", r"tier|platinum",
            id="unknown-tier",
        ),
    ],
)
def test_file_claim_rejects_bad_input(conn, passenger, flight, claim_type, tier, message):
    with pytest.raises(claims.ClaimError, match=message):
        claims.file_claim(conn, passenger, flight, claim_type, tier, NOW)

    assert row_count(conn, "claims") == 0
    assert row_count(conn, "history") == 0


def test_list_claims_filters_by_status_and_tier(conn):
    gold_open = claims.file_claim(conn, "Ada", "OA100", "lost", "gold", NOW)
    silver_open = claims.file_claim(conn, "Grace", "OA200", "delayed", "silver", NOW)
    gold_resolved = claims.file_claim(conn, "Alan", "OA300", "damaged", "gold", NOW)
    # Status changes belong to a later branch, so set one up directly.
    conn.execute("UPDATE claims SET status = 'resolved' WHERE id = ?", (gold_resolved,))

    def ids(rows):
        return {row["id"] for row in rows}

    assert ids(claims.list_claims(conn)) == {gold_open, silver_open, gold_resolved}
    assert ids(claims.list_claims(conn, status="open")) == {gold_open, silver_open}
    assert ids(claims.list_claims(conn, tier="gold")) == {gold_open, gold_resolved}
    assert ids(claims.list_claims(conn, status="open", tier="gold")) == {gold_open}
    assert ids(claims.list_claims(conn, status="closed")) == set()


# --- feature/assign-and-status ---

# Allowed status changes, copied from PLAN.md section 2. Written out here so the
# tests check claims.ALLOWED_CHANGES against the plan, not against itself.
PLAN_ALLOWED_CHANGES = {
    "open": {"assigned", "escalated"},
    "assigned": {"resolved", "escalated"},
    "escalated": {"assigned", "resolved"},
    "resolved": {"closed"},
    "closed": set(),
}

# A fixed time well past every tier's deadline (72h max) for status changes.
LATER = NOW + timedelta(days=5)


def file_with_status(conn, status):
    """File a claim, then set its status directly (setup only)."""
    claim_id = claims.file_claim(conn, "Ada", "OA100", "lost", "gold", NOW)
    conn.execute("UPDATE claims SET status = ? WHERE id = ?", (status, claim_id))
    return claim_id


def test_assign_open_claim_sets_agent_and_status(conn):
    claim_id = claims.file_claim(conn, "Ada", "OA100", "lost", "gold", NOW)

    claims.assign_claim(conn, claim_id, "agent-ana", LATER)

    claim = claims.get_claim(conn, claim_id)
    assert claim["agent"] == "agent-ana"
    assert claim["status"] == "assigned"


def test_every_allowed_change_works(conn):
    assert claims.ALLOWED_CHANGES == PLAN_ALLOWED_CHANGES

    for old_status, new_statuses in PLAN_ALLOWED_CHANGES.items():
        for new_status in new_statuses:
            claim_id = file_with_status(conn, old_status)

            claims.change_status(conn, claim_id, new_status, "agent-ana", LATER)

            assert claims.get_claim(conn, claim_id)["status"] == new_status, (
                f"{old_status} -> {new_status} should be allowed"
            )


@pytest.mark.parametrize(
    ("old_status", "new_status"),
    [
        pytest.param("open", "closed", id="open-to-closed"),
        pytest.param("resolved", "assigned", id="resolved-to-assigned"),
        pytest.param("closed", "open", id="closed-to-open"),
    ],
)
def test_disallowed_change_is_rejected(conn, old_status, new_status):
    claim_id = file_with_status(conn, old_status)

    with pytest.raises(claims.ClaimError, match=new_status):
        claims.change_status(conn, claim_id, new_status, "agent-ana", LATER)

    assert claims.get_claim(conn, claim_id)["status"] == old_status


def test_change_adds_history_and_refused_change_leaves_everything(conn):
    claim_id = claims.file_claim(conn, "Ada", "OA100", "lost", "gold", NOW)

    claims.change_status(conn, claim_id, "assigned", "agent-ana", LATER)

    history = claims.get_history(conn, claim_id)
    assert len(history) == 2
    entry = history[-1]
    assert entry["old_status"] == "open"
    assert entry["new_status"] == "assigned"
    assert entry["changed_by"] == "agent-ana"
    assert as_datetime(entry["changed_at"]) == LATER

    before = dict(claims.get_claim(conn, claim_id))
    with pytest.raises(claims.ClaimError):
        claims.change_status(conn, claim_id, "closed", "agent-ana", LATER)

    assert dict(claims.get_claim(conn, claim_id)) == before
    assert len(claims.get_history(conn, claim_id)) == 2


# --- feature/deadlines-and-escalation ---

GOLD_DEADLINE = NOW + timedelta(hours=4)


def test_deadline_by_tier(conn):
    expected_hours = {"gold": 4, "silver": 24, "standard": 72}

    for tier, hours in expected_hours.items():
        claim_id = claims.file_claim(conn, "Ada", "OA100", "lost", tier, NOW)

        deadline = as_datetime(claims.get_claim(conn, claim_id)["deadline"])
        assert deadline == NOW + timedelta(hours=hours), f"{tier} should get {hours}h"


@pytest.mark.parametrize(
    ("check_time", "expected"),
    [
        pytest.param(GOLD_DEADLINE - timedelta(minutes=1), False, id="1-min-before"),
        pytest.param(GOLD_DEADLINE, False, id="exactly-at"),
        pytest.param(GOLD_DEADLINE + timedelta(minutes=1), True, id="1-min-after"),
    ],
)
def test_is_overdue_at_gold_deadline_edge(conn, check_time, expected):
    claim_id = claims.file_claim(conn, "Ada", "OA100", "lost", "gold", NOW)
    claim = claims.get_claim(conn, claim_id)

    assert claims.is_overdue(claim, check_time) is expected


def test_escalate_overdue_escalates_only_overdue_open_and_assigned(conn):
    check_time = NOW + timedelta(hours=5)  # past gold (4h), before silver (24h)

    overdue_open = file_with_status(conn, "open")  # gold
    overdue_assigned = file_with_status(conn, "assigned")  # gold
    not_yet_overdue = claims.file_claim(conn, "Grace", "OA200", "delayed", "silver", NOW)
    resolved = file_with_status(conn, "resolved")  # gold, past deadline
    closed = file_with_status(conn, "closed")  # gold, past deadline

    escalated_ids = claims.escalate_overdue(conn, check_time)

    assert sorted(escalated_ids) == sorted([overdue_open, overdue_assigned])
    for claim_id, old_status in [(overdue_open, "open"), (overdue_assigned, "assigned")]:
        assert claims.get_claim(conn, claim_id)["status"] == "escalated"
        entry = claims.get_history(conn, claim_id)[-1]
        assert entry["old_status"] == old_status
        assert entry["new_status"] == "escalated"
        assert entry["changed_by"] == "system"
        assert as_datetime(entry["changed_at"]) == check_time

    for claim_id, status in [
        (not_yet_overdue, "open"),
        (resolved, "resolved"),
        (closed, "closed"),
    ]:
        assert claims.get_claim(conn, claim_id)["status"] == status
        assert len(claims.get_history(conn, claim_id)) == 1  # only the filing row


def test_failed_history_write_rolls_back_status_change(conn):
    claim_id = claims.file_claim(conn, "Ada", "OA100", "lost", "gold", NOW)
    history_before = len(claims.get_history(conn, claim_id))
    # Make every later history insert fail on purpose.
    conn.execute(
        "CREATE TRIGGER fail_history BEFORE INSERT ON history"
        " BEGIN SELECT RAISE(ABORT, 'history write failed on purpose'); END"
    )

    with pytest.raises(sqlite3.DatabaseError, match="history write failed"):
        claims.change_status(conn, claim_id, "assigned", "agent-ana", LATER)

    assert claims.get_claim(conn, claim_id)["status"] == "open"
    assert len(claims.get_history(conn, claim_id)) == history_before
