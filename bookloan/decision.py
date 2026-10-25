"""The loan decision service.

A loan request ends in one of three decisions:  APPROVED / WAITLISTED / REJECTED.
Stores used by the decision:
  PostgreSQL : member status, fines, active loans, stock; the transaction that saves the loan + decision
  MongoDB    : the book's min_age (flexible catalogue record)
  Redis      : cache of the decision (cache-aside, with TTL)
Neo4j and the vector stores are used afterwards to suggest ALTERNATIVES (see recommend.py).

Rule order (the first rule that fails decides; documented in tests/eligibility_cases.json):
  1 member exists  2 book exists  3 member active  4 fines <= 5.00  5 active loans < 3
  6 not already holding this book  7 age >= book min_age  8 copy available? APPROVED : WAITLISTED
"""
import json
import time
from datetime import datetime, timezone

from . import config
from .db import mongo, pg, rds


def evaluate(conn, mdb, member_id, book_id, lock=False):
    """Apply the rules and return (outcome, reason_code).
    lock=True takes a row lock on the book (SELECT ... FOR UPDATE) -- used inside the real transaction."""
    member = conn.execute("SELECT status, fines_eur, birth_year FROM members WHERE member_id=%s", (member_id,)).fetchone()
    if member is None:
        return "REJECTED", "MEMBER_NOT_FOUND"
    book = conn.execute("SELECT copies_available FROM books WHERE book_id=%s" + (" FOR UPDATE" if lock else ""),
                        (book_id,)).fetchone()
    if book is None:
        return "REJECTED", "BOOK_NOT_FOUND"
    status, fines, birth_year = member
    if status != "active":
        return "REJECTED", "SUSPENDED"
    if float(fines) > config.FINE_LIMIT_EUR:
        return "REJECTED", "UNPAID_FINES"
    active = conn.execute("SELECT count(*) FROM loans WHERE member_id=%s AND returned_at IS NULL", (member_id,)).fetchone()[0]
    if active >= config.MAX_ACTIVE_LOANS:
        return "REJECTED", "LOAN_LIMIT"
    holds = conn.execute("SELECT 1 FROM loans WHERE member_id=%s AND book_id=%s AND returned_at IS NULL",
                         (member_id, book_id)).fetchone()
    if holds:
        return "REJECTED", "ALREADY_BORROWED"
    doc = mdb.books.find_one({"_id": book_id}, {"min_age": 1})            # <- the MongoDB part of the decision
    min_age = doc["min_age"] if doc else 0
    if config.REFERENCE_YEAR - birth_year < min_age:
        return "REJECTED", "AGE_RESTRICTED"
    if book[0] > 0:
        return "APPROVED", "OK"
    return "WAITLISTED", "NO_COPIES"


# ---------- Redis: cache-aside read of a decision --------------------------------------------
def cache_key(member_id, book_id):
    return f"loan:{member_id}:{book_id}:decision"


def preview_decision(member_id, book_id, use_cache=True):
    """What would the decision be right now? (read only, nothing is saved in PostgreSQL)
    Cache-aside: look in Redis first; on a miss compute from PostgreSQL+MongoDB and store with a TTL.
    Returns (outcome, code, source) where source is 'cache' or 'db'."""
    r = rds()
    key = cache_key(member_id, book_id)
    if use_cache:
        hit = r.get(key)
        if hit:
            d = json.loads(hit)
            return d["outcome"], d["code"], "cache"
    with pg() as conn:
        outcome, code = evaluate(conn, mongo(), member_id, book_id)
    if use_cache:
        r.set(key, json.dumps({"outcome": outcome, "code": code,
                               "refreshed_at": datetime.now(timezone.utc).isoformat()}),
              ex=config.DECISION_TTL_SECONDS)
    return outcome, code, "db"


def invalidate_member(member_id):
    """Delete every cached decision of one member (called in the same code path as the update)."""
    r = rds()
    n = 0
    for k in r.scan_iter(f"loan:{member_id}:*:decision"):
        n += r.delete(k)
    return n


def suspend_member(member_id, invalidate=True):
    """Update the source (PostgreSQL). With invalidate=True the derived Redis entries are deleted in
    the same function, so the next read reloads the new decision."""
    with pg() as conn:
        conn.execute("UPDATE members SET status='suspended' WHERE member_id=%s", (member_id,))
    return invalidate_member(member_id) if invalidate else 0


# ---------- the real transaction -----------------------------------------------------------
def request_loan(member_id, book_id, safe=True, pause=0.0):
    """Decide and, if approved, lend -- all in ONE PostgreSQL transaction.
    safe=True : lock the book row first (SELECT ... FOR UPDATE), so two requests for the last copy
                are processed one after the other.
    safe=False: no lock (only used in the concurrency experiment to show what the lock prevents).
    pause     : seconds to sleep between the check and the write (makes the race easy to trigger)."""
    mdb = mongo()
    with pg() as conn:                      # leaving the 'with' block commits (or rolls back on error)
        outcome, code = evaluate(conn, mdb, member_id, book_id, lock=safe)
        if pause:
            time.sleep(pause)
        req_id = conn.execute("INSERT INTO loan_requests (member_id, book_id) VALUES (%s,%s) RETURNING request_id",
                              (member_id, book_id)).fetchone()[0] if code not in ("MEMBER_NOT_FOUND",) else None
        if outcome == "APPROVED":
            conn.execute("INSERT INTO loans (member_id, book_id, loaned_at, due_at) "
                         "VALUES (%s,%s,current_date,current_date + 21)", (member_id, book_id))
            conn.execute("UPDATE books SET copies_available = copies_available - 1 WHERE book_id=%s", (book_id,))
        if req_id:
            conn.execute("INSERT INTO decisions (request_id, outcome, reason_code) VALUES (%s,%s,%s)",
                         (req_id, outcome, code))
    rds().delete(cache_key(member_id, book_id))           # derived cache entry is now outdated
    return outcome, code
