"""Experiments for the non-vector parts. Every function RETURNS a dict of numbers/observations;
nothing in the report is typed by hand -- run_all.py prints them and saves them to results/.
"""
import json
import threading
from datetime import datetime, timezone

import pymongo

from . import config, decision, recommend, refresh
from .db import mongo, neo, pg, qdrant, rds
from .embed import embed


def eligibility():
    """17 labelled test cases (tests/eligibility_cases.json, written before the code)."""
    cases = json.loads((config.ROOT / "tests" / "eligibility_cases.json").read_text(encoding="utf-8"))["cases"]
    mdb, failures = mongo(), []
    with pg() as conn:
        for c in cases:
            got = decision.evaluate(conn, mdb, c["member"], c["book"])
            if got != (c["expect"], c["code"]):
                failures.append({"case": c["id"], "expected": [c["expect"], c["code"]], "got": list(got)})
    return {"cases": len(cases), "passed": len(cases) - len(failures), "failures": failures}


def concurrency():
    """Two members ask for the LAST copy of a book at the same moment."""
    def race(book_id, safe, pause):
        out = {}
        barrier = threading.Barrier(2)

        def worker(member):
            barrier.wait()                              # both start together
            try:
                out[member] = decision.request_loan(member, book_id, safe=safe, pause=pause)
            except Exception as e:                      # the DB refused the second write
                out[member] = ("ERROR", type(e).__name__)
        ts = [threading.Thread(target=worker, args=(m,)) for m in (9001, 9012)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        with pg() as conn:
            left = conn.execute("SELECT copies_available FROM books WHERE book_id=%s", (book_id,)).fetchone()[0]
        return {"results": {str(k): list(v) for k, v in out.items()}, "copies_left": left}

    safe = race("B0003", safe=True, pause=0.5)          # B0003 has exactly one copy (fixture)
    with pg() as conn:                                   # make B0006 a one-copy book for the unsafe run
        conn.execute("UPDATE books SET copies_available = 1 WHERE book_id='B0006'")
    unsafe = race("B0006", safe=False, pause=0.5)
    return {"with_row_lock": safe, "without_lock": unsafe}


def mongo_validation():
    """Inserting a book without a field required for its kind must fail."""
    db = mongo()
    before = db.books.count_documents({})
    base = {"ol_key": "/works/OL0W", "title": "Bad", "author": "A B", "genre": "poetry", "min_age": 0,
            "description": "A valid long description.", "updated_at": "2026-01-01T00:00:00Z"}
    bad = [("fiction without subject_people", {**base, "_id": "BAD1", "kind": "fiction", "subject_places": []}),
           ("nonfiction without subject_places", {**base, "_id": "BAD2", "kind": "nonfiction", "subject_people": []}),
           ("unknown kind", {**base, "_id": "BAD3", "kind": "audiobook"}),
           ("missing title", {k: v for k, v in {**base, "_id": "BAD4", "kind": "fiction", "subject_people": []}.items() if k != "title"})]
    res = {}
    for name, doc in bad:
        try:
            db.books.insert_one(doc)
            res[name] = "INSERTED (validation did not fire!)"
        except pymongo.errors.WriteError as e:
            res[name] = f"rejected, error code {e.code} (DocumentValidationFailed)"
    good = {**base, "_id": "GOOD1", "kind": "fiction", "subject_people": []}
    db.books.insert_one(good)
    db.books.delete_one({"_id": "GOOD1"})
    return {"results": res, "documents_before": before, "documents_after": db.books.count_documents({})}


def redis_cache():
    """Cache-aside, the stale value, and the fix (delete the key in the same update path)."""
    r = rds()
    out = {}
    m1, m2, book = 9001, 9005, "B0004"
    r.delete(decision.cache_key(m1, book), decision.cache_key(m2, book))

    a = decision.preview_decision(m1, book)
    b = decision.preview_decision(m1, book)
    out["1_first_read"] = {"outcome": a[0], "source": a[2]}
    out["2_second_read"] = {"outcome": b[0], "source": b[2], "ttl_seconds": r.ttl(decision.cache_key(m1, book))}

    # WRONG update path: change PostgreSQL but leave Redis alone
    decision.suspend_member(m1, invalidate=False)
    stale = decision.preview_decision(m1, book)
    truth = decision.preview_decision(m1, book, use_cache=False)
    out["3_after_suspend_without_invalidation"] = {"cached_answer": stale[0], "source": stale[2],
                                                    "real_answer_from_db": truth[0] + "/" + truth[1]}
    # RIGHT update path: update + delete the key together
    decision.preview_decision(m2, book)
    deleted = decision.suspend_member(m2, invalidate=True)
    fresh = decision.preview_decision(m2, book)
    out["4_after_suspend_with_invalidation"] = {"keys_deleted": deleted, "next_read_source": fresh[2],
                                                 "answer": fresh[0] + "/" + fresh[1]}
    with pg() as conn:                                  # restore, so later experiments see normal members
        conn.execute("UPDATE members SET status='active' WHERE member_id IN (%s,%s)", (m1, m2))
    decision.invalidate_member(m1)
    decision.invalidate_member(m2)
    return out


def graph():
    out = {}
    with neo().session() as s:
        out["nodes"] = {r["l"]: r["n"] for r in s.run("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS n")}
        out["relationships"] = {r["t"]: r["n"] for r in s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n")}
    same_author, also = recommend.graph_alternatives("B0002")
    with pg() as conn:
        avail = conn.execute("SELECT book_id, copies_available FROM books WHERE book_id = ANY(%s) ORDER BY book_id",
                             (same_author + [i for i, _ in also],)).fetchall()
    out["waitlisted_book"] = "B0002"
    out["same_author_ids"] = same_author
    out["share_most_subjects"] = recommend.graph_shared_subjects("B0002")
    out["readers_also_borrowed"] = also
    out["of_these_available_now (PostgreSQL)"] = [b for b, c in avail if c > 0]
    return out


def update_across_stores():
    """Change ONE source record in MongoDB and watch the derived copies go stale, then refresh them."""
    book, kid = "B0004", 9002
    new_desc = "A young dragon-rider and her dragon must stop a war between two mountain kingdoms."
    out = {}
    decision.preview_decision(kid, book)                              # fill the Redis cache
    out["before"] = {"redis_decision": decision.preview_decision(kid, book)[0::2],
                     "stale_books": refresh.find_stale()}
    old_desc = mongo().books.find_one({"_id": book})["description"]
    old_author = mongo().books.find_one({"_id": book})["author"]

    # ---- the one source update (MongoDB) ----
    mongo().books.update_one({"_id": book}, {"$set": {
        "min_age": 16, "description": new_desc, "author": "Corrected Author",
        "updated_at": datetime.now(timezone.utc).isoformat()}})

    def rank(text, system):
        v = embed([text])[0]
        if system == "pgvector":
            from pgvector.psycopg import register_vector
            with pg() as conn:
                register_vector(conn)
                ids = [r[0] for r in conn.execute("SELECT book_id FROM book_embeddings ORDER BY embedding <=> %s LIMIT 10", (v,))]
        else:
            ids = [h.payload["book_id"] for h in qdrant().query_points(config.QDRANT_COLLECTION, query=v.tolist(), limit=10, with_payload=True).points]
        return ids.index(book) + 1 if book in ids else None

    def state(label):
        with neo().session() as s:
            author_in_graph = s.run("MATCH (:Book {book_id:$b})-[:WRITTEN_BY]->(a) RETURN a.name AS n", b=book).single()["n"]
        d = decision.preview_decision(kid, book)
        real = decision.preview_decision(kid, book, use_cache=False)
        return {"redis_says": d[0] + "(" + d[2] + ")", "real_decision": real[0] + "/" + real[1],
                "graph_author": author_in_graph,
                "rank_of_book_for_NEW_description (pgvector, qdrant)": [rank(new_desc, "pgvector"), rank(new_desc, "qdrant")],
                "rank_of_book_for_OLD_description (pgvector, qdrant)": [rank(old_desc, "pgvector"), rank(old_desc, "qdrant")],
                "stale_books_detected": refresh.find_stale()}

    out["mongo_old_author"] = old_author
    out["after_mongo_update_BEFORE_refresh"] = state("stale")
    out["redis_keys_deleted_by_refresh"] = refresh.refresh_book(book)
    out["after_refresh"] = state("fresh")
    return out
