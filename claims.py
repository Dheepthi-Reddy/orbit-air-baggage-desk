"""Filing and looking up baggage claims.

The current time is always passed in as ``now``; this module never reads the
real clock. Times are stored as ISO-8601 strings.
"""

from datetime import datetime, timedelta

CLAIM_TYPES = ("delayed", "lost", "damaged")
TIERS = ("gold", "silver", "standard")
STATUSES = ("open", "assigned", "escalated", "resolved", "closed")
DEADLINE_HOURS = {"gold": 4, "silver": 24, "standard": 72}

# Allowed status changes (PLAN.md section 2): status -> statuses it may move to.
ALLOWED_CHANGES = {
    "open": {"assigned", "escalated"},
    "assigned": {"resolved", "escalated"},
    "escalated": {"assigned", "resolved"},
    "resolved": {"closed"},
    "closed": set(),
}

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
        _write_history(conn, claim_id, None, "open", FILED_BY, filed_at)
    return claim_id


def _write_history(conn, claim_id, old_status, new_status, changed_by, changed_at):
    """Insert one history row. Callers run this inside their own transaction."""
    conn.execute(
        "INSERT INTO history"
        " (claim_id, old_status, new_status, changed_by, changed_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (claim_id, old_status, new_status, changed_by, changed_at),
    )


def _apply_change(conn, claim_id, new_status, changed_by, now, agent=None):
    """Check and apply one status change, plus its history row, atomically.

    If ``agent`` is given it is saved on the claim in the same update.
    """
    _require_choice("status", new_status, STATUSES)
    _require_text("changed_by", changed_by)
    _require_datetime("now", now)

    old_status = get_claim(conn, claim_id)["status"]  # raises if no such claim
    allowed = ALLOWED_CHANGES[old_status]
    if new_status not in allowed:
        options = ", ".join(sorted(allowed)) or "nothing (final status)"
        raise ClaimError(
            f"claim {claim_id} cannot change from {old_status!r} to "
            f"{new_status!r}; from {old_status!r} it can go to: {options}"
        )

    changed_at = now.isoformat()
    with conn:  # one transaction: status update and history row together
        if agent is None:
            conn.execute(
                "UPDATE claims SET status = ? WHERE id = ?", (new_status, claim_id)
            )
        else:
            conn.execute(
                "UPDATE claims SET status = ?, agent = ? WHERE id = ?",
                (new_status, agent, claim_id),
            )
        _write_history(conn, claim_id, old_status, new_status, changed_by, changed_at)


def change_status(conn, claim_id, new_status, changed_by, now):
    """Move a claim to ``new_status`` if ALLOWED_CHANGES permits it."""
    _apply_change(conn, claim_id, new_status, changed_by, now)


def assign_claim(conn, claim_id, agent, now):
    """Assign an open or escalated claim to ``agent``; the agent is recorded as who."""
    _require_text("agent", agent)
    _apply_change(conn, claim_id, "assigned", agent, now, agent=agent)


def resolve_claim(conn, claim_id, changed_by, now):
    """Resolve an assigned or escalated claim."""
    change_status(conn, claim_id, "resolved", changed_by, now)


def close_claim(conn, claim_id, changed_by, now):
    """Close a resolved claim."""
    change_status(conn, claim_id, "closed", changed_by, now)


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
