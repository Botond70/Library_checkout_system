"""Alternatives for a waitlisted / rejected request. Uses the graph store and the vector stores.

Graph (Neo4j)   : "structural" neighbours -- same author, shared subjects, what other readers also borrowed
Vectors         : "semantic" neighbours   -- books whose description is similar
Both only return book ids; PostgreSQL then says which of them can be borrowed right now.
"""
from . import config
from .db import neo, pg, qdrant
from .embed import embed
from pgvector.psycopg import register_vector
from qdrant_client import models as qm


def graph_alternatives(book_id, limit=5):
    """Other books by the same author, books sharing the most subjects, plus 'readers also borrowed'."""
    with neo().session() as s:
        same_author = s.run("""MATCH (:Book {book_id:$id})-[:WRITTEN_BY]->(a)<-[:WRITTEN_BY]-(o:Book)
                               WHERE o.book_id <> $id RETURN o.book_id AS id LIMIT $n""", id=book_id, n=limit)
        a = [r["id"] for r in same_author]
        also = s.run("""MATCH (:Book {book_id:$id})<-[:BORROWED]-(m:Member)-[:BORROWED]->(o:Book)
                        WHERE o.book_id <> $id
                        RETURN o.book_id AS id, count(DISTINCT m) AS readers
                        ORDER BY readers DESC, id LIMIT $n""", id=book_id, n=limit)
        b = [(r["id"], r["readers"]) for r in also]
    return a, b


def graph_shared_subjects(book_id, limit=5):
    """Books that share the most (real Open Library) subjects with this one: (book_id, shared_subjects)."""
    with neo().session() as s:
        rows = s.run("""MATCH (:Book {book_id:$id})-[:HAS_SUBJECT]->(x)<-[:HAS_SUBJECT]-(o:Book)
                        WHERE o.book_id <> $id
                        RETURN o.book_id AS id, count(x) AS shared ORDER BY shared DESC, id LIMIT $n""", id=book_id, n=limit)
        return [(r["id"], r["shared"]) for r in rows]


def similar_pgvector_joined(description_vec, genre=None, limit=5):
    """ONE SQL statement: nearest descriptions (pgvector) joined with the business table `books`
    so only books that can be borrowed right now are returned."""
    sql = """SELECT b.book_id, b.title, b.copies_available, e.embedding <=> %s AS cosine_distance
             FROM book_embeddings e JOIN books b USING (book_id)
             WHERE b.copies_available > 0 AND (%s::text IS NULL OR e.genre = %s)
             ORDER BY e.embedding <=> %s LIMIT %s"""
    with pg() as conn:
        register_vector(conn)
        return conn.execute(sql, (description_vec, genre, genre, description_vec, limit)).fetchall()


def similar_qdrant_then_pg(description_vec, genre=None, limit=5):
    """The same question with Qdrant: Qdrant cannot see PostgreSQL, so it takes TWO steps.
    1) Qdrant returns the nearest ids (we ask for more than `limit`, because some may be out of stock)
    2) PostgreSQL filters those ids by availability.  Over-fetching is a guess: if too many are out of
       stock we may return fewer than `limit` rows -- the weakness of the two-step approach."""
    flt = qm.Filter(must=[qm.FieldCondition(key="genre", match=qm.MatchValue(value=genre))]) if genre else None
    hits = qdrant().query_points(config.QDRANT_COLLECTION, query=description_vec.tolist(), query_filter=flt,
                                 limit=limit * 4, with_payload=True).points
    ids = [h.payload["book_id"] for h in hits]
    score = {h.payload["book_id"]: h.score for h in hits}
    with pg() as conn:
        rows = conn.execute("SELECT book_id, title, copies_available FROM books "
                            "WHERE book_id = ANY(%s) AND copies_available > 0", (ids,)).fetchall()
    rows.sort(key=lambda r: -score[r[0]])
    return [(r[0], r[1], r[2], 1 - score[r[0]]) for r in rows[:limit]]


def text_to_vec(text):
    return embed([text])[0]
