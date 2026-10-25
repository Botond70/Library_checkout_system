"""Keeping DERIVED copies in sync with the source of truth.

Source of truth for a catalogue record = MongoDB (field `updated_at`).
Derived copies:  Redis cached decisions, pgvector row, Qdrant point, Neo4j Book->Author edge.
Each derived vector row keeps `refreshed_at`; a record is STALE when Mongo's updated_at is newer.
Nothing here is automatic: the derived copies stay stale until refresh_book() is called.
"""
from datetime import datetime, timezone

from pgvector.psycopg import register_vector
from qdrant_client import models as qm

from . import config
from .db import mongo, neo, pg, qdrant, rds
from .embed import embed


def _qdrant_id(book_id):
    return int(book_id[1:]) - 1          # B0001 -> point 0 (same numbering as load_all.py)


def find_stale():
    """Books whose Mongo record is newer than their vector copy."""
    with pg() as conn:
        refreshed = dict(conn.execute("SELECT book_id, refreshed_at FROM book_embeddings").fetchall())
    stale = []
    for d in mongo().books.find({}, {"updated_at": 1}):
        updated = datetime.fromisoformat(d["updated_at"].replace("Z", "+00:00"))
        if updated > refreshed[d["_id"]]:
            stale.append(d["_id"])
    return stale


def refresh_book(book_id):
    doc = mongo().books.find_one({"_id": book_id})
    now = datetime.now(timezone.utc)
    vec = embed([doc["description"]])[0]
    with pg() as conn:
        register_vector(conn)
        conn.execute("UPDATE book_embeddings SET embedding=%s, genre=%s, refreshed_at=%s WHERE book_id=%s",
                     (vec, doc["genre"], now, book_id))
        conn.execute("UPDATE books SET title=%s, genre=%s WHERE book_id=%s", (doc["title"], doc["genre"], book_id))
    qdrant().upsert(config.QDRANT_COLLECTION, points=[qm.PointStruct(
        id=_qdrant_id(book_id), vector=vec.tolist(),
        payload={"book_id": book_id, "genre": doc["genre"], "refreshed_at": now.isoformat()})])
    with neo().session() as s:
        s.run("""MATCH (b:Book {book_id:$id}) OPTIONAL MATCH (b)-[old:WRITTEN_BY]->() DELETE old
                 WITH DISTINCT b MERGE (a:Author {name:$author}) MERGE (b)-[:WRITTEN_BY]->(a)
                 SET b.title=$title, b.refreshed_at=$now""",
              id=book_id, author=doc["author"], title=doc["title"], now=now.isoformat())
    r = rds()
    return sum(r.delete(k) for k in r.scan_iter(f"loan:*:{book_id}:decision"))
