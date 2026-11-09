"""Command line interface for the Orbit Air baggage desk.

Usage: python main.py [--db PATH] [--now ISO] <command> ...

This file only reads arguments, picks the clock, calls claims.py, and prints
the result. All rules live in claims.py. This is the only module that reads
the real clock, and only when --now is not given.
"""

import argparse
import contextlib
import csv
import sqlite3
import sys
from datetime import UTC, datetime

import claims
import db

DEFAULT_DB = "baggage.db"
SEED_COLUMNS = ("passenger", "flight", "type", "tier", "note")


def parse_now(value):
    """Parse an ISO timestamp for --now. One without a timezone is treated as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid ISO timestamp {value!r}, e.g. 2026-11-02T14:00:00"
        ) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build_parser():
    parser = argparse.ArgumentParser(prog="main.py", description="Orbit Air baggage desk")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"database file (default {DEFAULT_DB})")
    parser.add_argument(
        "--now", type=parse_now, help="use this ISO time instead of the real clock"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("file", help="file a new claim")
    p.add_argument("--passenger", required=True)
    p.add_argument("--flight", required=True)
    p.add_argument("--type", required=True, dest="claim_type", help="delayed, lost, or damaged")
    p.add_argument("--tier", required=True, help="gold, silver, or standard")
    p.add_argument("--note")

    p = sub.add_parser("list", help="list claims")
    p.add_argument("--status")
    p.add_argument("--tier")

    p = sub.add_parser("assign", help="assign an open or escalated claim to an agent")
    p.add_argument("id", type=int)
    p.add_argument("agent")

    p = sub.add_parser("resolve", help="resolve an assigned or escalated claim")
    p.add_argument("id", type=int)
    p.add_argument("--by", required=True, help="who is making the change")

    p = sub.add_parser("close", help="close a resolved claim")
    p.add_argument("id", type=int)
    p.add_argument("--by", required=True, help="who is making the change")

    p = sub.add_parser("escalate", help="escalate every overdue open or assigned claim")
    p.add_argument("--by", default="system", help="who is making the change (default system)")

    p = sub.add_parser("history", help="show one claim's history")
    p.add_argument("id", type=int)

    p = sub.add_parser("seed", help="load claims from a CSV file")
    p.add_argument("csv_path")

    return parser


def printable(text):
    """Replace newlines and control characters so free text stays on one line."""
    return "".join(ch if ch.isprintable() else " " for ch in text)


def format_claim(row):
    return (
        f"#{row['id']}  {row['status']:<9} {row['tier']:<8} {row['claim_type']:<7} "
        f"{printable(row['flight']):<7} {printable(row['passenger'])}  "
        f"agent={printable(row['agent'] or '-')}  "
        f"deadline={row['deadline']}  note={printable(row['note'] or '-')}"
    )


def cmd_file(conn, args, now):
    claim_id = claims.file_claim(
        conn, args.passenger, args.flight, args.claim_type, args.tier, now, note=args.note
    )
    claim = claims.get_claim(conn, claim_id)
    print(f"Filed claim {claim_id} (deadline {claim['deadline']})")


def cmd_list(conn, args, now):
    rows = claims.list_claims(conn, status=args.status, tier=args.tier)
    if not rows:
        print("No claims found.")
    for row in rows:
        print(format_claim(row))


def cmd_assign(conn, args, now):
    claims.assign_claim(conn, args.id, args.agent, now)
    print(f"Claim {args.id} assigned to {args.agent}")


def cmd_resolve(conn, args, now):
    claims.resolve_claim(conn, args.id, args.by, now)
    print(f"Claim {args.id} resolved")


def cmd_close(conn, args, now):
    claims.close_claim(conn, args.id, args.by, now)
    print(f"Claim {args.id} closed")


def cmd_escalate(conn, args, now):
    ids = claims.escalate_overdue(conn, now, changed_by=args.by)
    if ids:
        print(f"Escalated {len(ids)} claim(s): {', '.join(str(i) for i in ids)}")
    else:
        print("No overdue claims to escalate.")


def cmd_history(conn, args, now):
    claims.get_claim(conn, args.id)  # clear error if the claim doesn't exist
    for row in claims.get_history(conn, args.id):
        print(
            f"{row['changed_at']}  {row['old_status'] or '-':<9} -> "
            f"{row['new_status']:<9} by {printable(row['changed_by'])}"
        )


def cmd_seed(conn, args, now):
    # utf-8-sig also accepts the byte-order mark that Excel adds to "CSV UTF-8" files.
    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in SEED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise claims.ClaimError(
                f"{args.csv_path} is missing column(s): {', '.join(missing)}"
            )
        count = 0
        for line_no, row in enumerate(reader, start=2):  # line 1 is the header
            values = {column: (row[column] or "").strip() for column in SEED_COLUMNS}
            try:
                claims.file_claim(
                    conn, values["passenger"], values["flight"], values["type"], values["tier"],
                    now, note=values["note"] or None,
                )
            except claims.ClaimError as exc:
                raise claims.ClaimError(
                    f"{args.csv_path} line {line_no}: {exc} ({count} claim(s) loaded before it)"
                ) from None
            count += 1
    print(f"Loaded {count} claim(s) from {args.csv_path}")


COMMANDS = {
    "file": cmd_file,
    "list": cmd_list,
    "assign": cmd_assign,
    "resolve": cmd_resolve,
    "close": cmd_close,
    "escalate": cmd_escalate,
    "history": cmd_history,
    "seed": cmd_seed,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    now = args.now or datetime.now(UTC)  # the only place the real clock is read

    try:
        with contextlib.closing(db.connect(args.db)) as conn:
            db.create_tables(conn)
            COMMANDS[args.command](conn, args, now)
    except (claims.ClaimError, OSError, UnicodeDecodeError, csv.Error, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
