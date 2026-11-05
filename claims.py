"""Filing and looking up baggage claims.

The current time is always passed in as ``now``; this module never reads the
real clock. Times are stored as ISO-8601 strings.
"""

from datetime import datetime, timedelta

CLAIM_TYPES = ("delayed", "lost", "damaged")
TIERS = ("gold", "silver", "standard")
STATUSES = ("open", "assigned", "escalated", "resolved", "closed")
DEADLINE_HOURS = {"gold": 4, "silver": 24, "standard": 72}

# Who is recorded in history when a claim is first filed.
FILED_BY = "system"


class ClaimError(Exception):
    """A claim rule was broken. The message names the bad field or value."""


def _require_text(field, value):
    if not isinstance(value, str) or not value.strip():
        raise ClaimError(f"{field} must not be blank")


def _require_choice(field, value, choices):
    if value not in choices:
        raise ClaimError(
            f"unknown {field} {value!r}; expected one of: {', '.join(choices)}"
        )


def _require_datetime(field, value):
    if not isinstance(value, datetime):
        raise ClaimError(f"{field} must be a datetime, got {value!r}")


def file_claim(conn, passenger, flight, claim_type, tier, now, note=None):
    """File a new open claim and its first history row. Returns the claim id."""
    _require_text("passenger", passenger)
    _require_text("flight", flight)
    _require_choice("claim_type", claim_type, CLAIM_TYPES)
    _require_choice("tier", tier, TIERS)
    _require_datetime("now", now)

    filed_at = now.isoformat()
    deadline = (now + timedelta(hours=DEADLINE_HOURS[tier])).isoformat()

    with conn:  # one transaction: commits both rows, or rolls back both
        cursor = conn.execute(
            "INSERT INTO claims"
            " (passenger, flight, claim_type, tier, status, agent, note,"
            "  filed_at, deadline)"
            " VALUES (?, ?, ?, ?, 'open', NULL, ?, ?, ?)",
            (passenger, flight, claim_type, tier, note, filed_at, deadline),
        )
        claim_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO history"
            " (claim_id, old_status, new_status, changed_by, changed_at)"
            " VALUES (?, NULL, 'open', ?, ?)",
            (claim_id, FILED_BY, filed_at),
        )
    return claim_id


def get_claim(conn, claim_id):
    """Return one claim row, or raise ClaimError if there is no such claim."""
    row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        raise ClaimError(f"no claim with id {claim_id!r}")
    return row


def get_history(conn, claim_id):
    """Return the claim's history rows, oldest first."""
    return conn.execute(
        "SELECT * FROM history WHERE claim_id = ? ORDER BY id", (claim_id,)
    ).fetchall()


def list_claims(conn, status=None, tier=None):
    """Return claims, optionally filtered by status and/or tier, in id order."""
    conditions = []
    params = []
    if status is not None:
        _require_choice("status", status, STATUSES)
        conditions.append("status = ?")
        params.append(status)
    if tier is not None:
        _require_choice("tier", tier, TIERS)
        conditions.append("tier = ?")
        params.append(tier)

    sql = "SELECT * FROM claims"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY id"
    return conn.execute(sql, params).fetchall()
