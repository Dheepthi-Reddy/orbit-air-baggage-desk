"""Tests for branch feature/schema-and-filing (PLAN.md section 4.1)."""

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
