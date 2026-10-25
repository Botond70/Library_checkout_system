"""Load the generated data into all five stores (idempotent: drops and rebuilds everything).

Source of truth:
  PostgreSQL  <- members.json, loans.json, plus the business fields of books.json
  MongoDB     <- books.json (the full flexible catalogue record)
Derived copies (rebuilt from the above, each keeps the source id and a refreshed_at time):
  Neo4j, pgvector, Qdrant.   Redis fills itself on demand (see decision.py).
Run:  python -m bookloan.load_all
"""
import json
from datetime import datetime, timezone

from pgvector.psycopg import register_vector
from qdrant_client import models as qm

from . import config
from .db import pg, mongo, neo, qdrant, rds
from .embed import embed
from .mongo_schema import create_books_collection


def load_json(name):
    return json.loads((config.DATA_DIR / name).read_text(encoding="utf-8"))


def load_postgres(books, members, loans):
    with pg() as conn:
        conn.execute((config.ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO members VALUES (%(member_id)s,%(name)s,%(birth_year)s,%(status)s,%(fines_eur)s)", members)
            cur.executemany("INSERT INTO books VALUES (%(_id)s,%(title)s,%(genre)s,%(copies_total)s,%(copies_available)s)", books)
            cur.executemany("INSERT INTO loans (member_id,book_id,loaned_at,due_at,returned_at) "
                            "VALUES (%(member_id)s,%(book_id)s,%(loaned_at)s,%(due_at)s,%(returned_at)s)", loans)


def load_mongo(books):
    db = mongo()
    create_books_collection(db)           # drops and recreates the collection with its $jsonSchema validator
    db.books.insert_many(books)


def load_neo4j(books, loans):
    now = datetime.now(timezone.utc).isoformat()
    drv = neo()
    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
        s.run("CREATE CONSTRAINT book_id IF NOT EXISTS FOR (b:Book) REQUIRE b.book_id IS UNIQUE")
        s.run("CREATE CONSTRAINT member_id IF NOT EXISTS FOR (m:Member) REQUIRE m.member_id IS UNIQUE")
        s.run("""UNWIND $rows AS r
                 MERGE (b:Book {book_id: r._id}) SET b.title = r.title, b.refreshed_at = $now
                 MERGE (a:Author {name: r.author})
                 MERGE (b)-[:WRITTEN_BY]->(a)
                 FOREACH (_ IN CASE WHEN r.series IS NULL THEN [] ELSE [1] END |
                     MERGE (s:Series {name: r.series})
                     MERGE (b)-[:IN_SERIES {position: r.series_position}]->(s))""",
              rows=books, now=now)
        rows = [{"m": l["member_id"], "b": l["book_id"]} for l in loans]
        s.run("""UNWIND $rows AS r
                 MERGE (m:Member {member_id: r.m})
                 MERGE (b:Book {book_id: r.b})
                 MERGE (m)-[:BORROWED]->(b)""", rows=rows)
    drv.close()


def load_vectors(books):
    vecs = embed([b["description"] for b in books])
    now = datetime.now(timezone.utc)
    with pg() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO book_embeddings (book_id, genre, embedding, refreshed_at) VALUES (%s,%s,%s,%s)",
                            [(b["_id"], b["genre"], v, now) for b, v in zip(books, vecs)])
            cur.execute("CREATE INDEX book_emb_hnsw ON book_embeddings USING hnsw (embedding vector_cosine_ops) "
                        "WITH (m = 16, ef_construction = 64)")
            cur.execute("ANALYZE book_embeddings")

    q = qdrant()
    if q.collection_exists(config.QDRANT_COLLECTION):
        q.delete_collection(config.QDRANT_COLLECTION)
    q.create_collection(config.QDRANT_COLLECTION,
                        vectors_config=qm.VectorParams(size=config.EMBED_DIM, distance=qm.Distance.COSINE),
                        hnsw_config=qm.HnswConfigDiff(m=16, ef_construct=64))
    # payload index on the filtered field (required by the assignment, and makes filtered HNSW work well)
    q.create_payload_index(config.QDRANT_COLLECTION, "genre", qm.PayloadSchemaType.KEYWORD)
    q.upsert(config.QDRANT_COLLECTION, points=[
        qm.PointStruct(id=i, vector=v.tolist(),
                       payload={"book_id": b["_id"], "genre": b["genre"], "refreshed_at": now.isoformat()})
        for i, (b, v) in enumerate(zip(books, vecs))])


def main():
    books, members, loans = load_json("books.json"), load_json("members.json"), load_json("loans.json")
    rds().flushdb()
    load_postgres(books, members, loans)
    print("PostgreSQL loaded")
    load_mongo(books)
    print("MongoDB loaded")
    load_neo4j(books, loans)
    print("Neo4j loaded")
    load_vectors(books)
    print("pgvector + Qdrant loaded")


if __name__ == "__main__":
    main()
