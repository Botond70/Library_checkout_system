"""pgvector vs Qdrant on the SAME data: identical normalised all-MiniLM-L6-v2 vectors, cosine
distance, same text ids, the same 20 fixed queries (tests/vector_queries.json).

Measured (all numbers are returned in a dict and printed by run_all.py):
  A  ANN recall@10      HNSW top-10 versus the system's OWN exact top-10  (shared ids / 10)
  B  shared ids         how many of the 10 ids pgvector and Qdrant agree on
  C  labelled quality   recall@5 and MRR against the genre labels
  D  ~5% filter         results returned, ANN recall@10 and latency, with a genre filter (20 of 420 rows = 4.8%)
  E  joined query       the same business question answered in one SQL statement vs two steps
"""
import json
import re
import statistics
import time

import psycopg
from pgvector.psycopg import register_vector
from qdrant_client import QdrantClient, models as qm

from . import config, recommend
from .db import mongo, qdrant
from .embed import embed

EF_SEARCH = 40          # pgvector default, written down explicitly
QDRANT_HNSW_EF = 64     # Qdrant: ef used at search time (recorded in the results)
K = 10


def qid_to_book(i):
    return f"B{i + 1:04d}"


class PG:
    """One autocommit connection so that SET commands stay in force."""
    def __init__(self):
        # prepare_threshold=None: never turn statements into server-side prepared statements. Otherwise a plan
        # cached in "exact" mode (sequential scan) would silently be reused in "ANN" mode and hide the index.
        self.c = psycopg.connect(config.PG_DSN, autocommit=True, prepare_threshold=None)
        register_vector(self.c)

    def mode(self, kind, ef=EF_SEARCH, iterative="off"):
        if kind == "ann":                      # force the HNSW index (otherwise the planner may scan sequentially on 420 rows)
            self.c.execute("SET enable_seqscan = off; SET enable_indexscan = on; SET enable_bitmapscan = on")
        else:                                  # exact: no index -> sequential scan + sort = true nearest neighbours
            self.c.execute("SET enable_seqscan = on; SET enable_indexscan = off; SET enable_bitmapscan = off")
        self.c.execute(f"SET hnsw.ef_search = {int(ef)}")
        self.c.execute(f"SET hnsw.iterative_scan = {iterative}")

    def search(self, qv, genre=None, k=K):
        if genre is None:
            rows = self.c.execute("SELECT book_id FROM book_embeddings ORDER BY embedding <=> %s LIMIT %s", (qv, k)).fetchall()
        else:
            rows = self.c.execute("SELECT book_id FROM book_embeddings WHERE genre = %s ORDER BY embedding <=> %s LIMIT %s",
                                  (genre, qv, k)).fetchall()
        return [r[0] for r in rows]

    def plan(self, qv, genre=None):
        where = "WHERE genre = %s " if genre else ""
        args = ((genre,) if genre else ()) + (qv,)
        rows = self.c.execute(f"EXPLAIN SELECT book_id FROM book_embeddings {where}ORDER BY embedding <=> %s LIMIT 10", args).fetchall()
        text = " | ".join(r[0].strip() for r in rows)
        return re.sub(r"'\[[^\]]*\]'::vector", "<query vector>", text)


class QD:
    def __init__(self, grpc=False):
        self.q = QdrantClient(url=config.QDRANT_URL, prefer_grpc=True, check_compatibility=False) if grpc else qdrant()

    def search(self, qv, genre=None, exact=False, k=K):
        flt = qm.Filter(must=[qm.FieldCondition(key="genre", match=qm.MatchValue(value=genre))]) if genre else None
        pts = self.q.query_points(config.QDRANT_COLLECTION, query=qv.tolist(), query_filter=flt, limit=k, with_payload=True,
                                  search_params=qm.SearchParams(hnsw_ef=QDRANT_HNSW_EF, exact=exact)).points
        return [p.payload["book_id"] for p in pts]


def timed(fn, repeats=3):
    """Median latency of fn() in milliseconds (fn is called `repeats` times; first call = warm-up is not counted)."""
    fn()
    t = []
    for _ in range(repeats):
        s = time.perf_counter()
        fn()
        t.append((time.perf_counter() - s) * 1000)
    return statistics.median(t)


def overlap(a, b, k=K):
    return len(set(a) & set(b)) / k


def run():
    spec = json.loads((config.ROOT / "tests" / "vector_queries.json").read_text(encoding="utf-8"))["queries"]
    qvecs = embed([q["text"] for q in spec])
    topic_of = {d["_id"]: d["genre"] for d in mongo().books.find({}, {"genre": 1})}
    pg, qd = PG(), QD()
    out = {}

    # ---- settings that must be recorded ----
    ext = pg.c.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
    pg.mode("ann")
    out["settings"] = {
        "pgvector_version": ext,
        "pgvector hnsw.ef_search": pg.c.execute("SHOW hnsw.ef_search").fetchone()[0],
        "pgvector hnsw.iterative_scan (main runs)": pg.c.execute("SHOW hnsw.iterative_scan").fetchone()[0],
        "pgvector index": "hnsw (vector_cosine_ops), m=16, ef_construction=64",
        "qdrant hnsw_ef": QDRANT_HNSW_EF,
        "qdrant hnsw": "m=16, ef_construct=64, cosine",
        "qdrant payload index": "genre (keyword)",
        "rows": pg.c.execute("SELECT count(*) FROM book_embeddings").fetchone()[0],
        "queries": len(spec),
    }
    out["settings"]["pgvector plan (ANN, unfiltered)"] = pg.plan(qvecs[0])

    # ---- A: ANN recall@10 against own exact top-10 ----
    pg_ann, pg_ex, qd_ann, qd_ex = [], [], [], []
    pg.mode("ann")
    pg_ann = [pg.search(v) for v in qvecs]
    pg.mode("exact")
    pg_ex = [pg.search(v) for v in qvecs]
    qd_ann = [qd.search(v) for v in qvecs]
    qd_ex = [qd.search(v, exact=True) for v in qvecs]
    out["A_ann_recall_at_10"] = {
        "pgvector": round(statistics.mean(overlap(a, e) for a, e in zip(pg_ann, pg_ex)), 4),
        "qdrant": round(statistics.mean(overlap(a, e) for a, e in zip(qd_ann, qd_ex)), 4),
    }

    # ---- B: shared ids between the two systems ----
    shared_ann = [len(set(a) & set(b)) for a, b in zip(pg_ann, qd_ann)]
    shared_ex = [len(set(a) & set(b)) for a, b in zip(pg_ex, qd_ex)]
    out["B_shared_ids_in_top10"] = {
        "ANN vs ANN: mean / min": [round(statistics.mean(shared_ann), 2), min(shared_ann)],
        "exact vs exact: mean / min": [round(statistics.mean(shared_ex), 2), min(shared_ex)],
        "per_query_ANN": shared_ann,
    }

    # ---- C: labelled quality (recall@5 = relevant in top-5 / 5; MRR over the top-10) ----
    def quality(results):
        rec, rr = [], []
        for q, ids in zip(spec, results):
            rel = [topic_of[i] == q["genre"] for i in ids]
            rec.append(sum(rel[:5]) / 5)
            rr.append(next((1 / (n + 1) for n, ok in enumerate(rel) if ok), 0))
        return {"recall@5": round(statistics.mean(rec), 4), "MRR": round(statistics.mean(rr), 4)}
    out["C_labelled_quality"] = {"pgvector": quality(pg_ann), "qdrant": quality(qd_ann)}

    # ---- latency, unfiltered ----
    pg.mode("ann")
    lat_pg = statistics.median(timed(lambda v=v: pg.search(v)) for v in qvecs)
    lat_qd = statistics.median(timed(lambda v=v: qd.search(v)) for v in qvecs)
    qd_grpc = QD(grpc=True)
    lat_qg = statistics.median(timed(lambda v=v: qd_grpc.search(v)) for v in qvecs)
    out["latency_unfiltered_ms_median"] = {"pgvector": round(lat_pg, 2), "qdrant (REST)": round(lat_qd, 2),
                                           "qdrant (gRPC)": round(lat_qg, 2)}

    # ---- D: filter that keeps ~5% of the rows ----
    genres = [q["genre"] for q in spec]
    n_genre = pg.c.execute("SELECT count(*) FROM book_embeddings WHERE genre=%s", (genres[0],)).fetchone()[0]
    out["D_filter"] = {"rows_kept": f"{n_genre} of {out['settings']['rows']} = {100 * n_genre / out['settings']['rows']:.1f}%"}

    # two filter styles: ON-topic (filter genre = the genre of the query) and OFF-topic (a different, unrelated genre,
    # e.g. "bread recipes ... but only inside 'horror'"): off-topic is the hard case, since the nearest vectors
    # are almost all outside the filter.
    off_genres = [genres[(i + 7) % len(genres)] for i in range(len(genres))]
    for style, gl in (("on_topic_filter", genres), ("off_topic_filter", off_genres)):
        section = {}
        # exact reference with the same filter
        pg.mode("exact")
        ref_pg = [pg.search(v, g) for v, g in zip(qvecs, gl)]
        ref_qd = [qd.search(v, g, exact=True) for v, g in zip(qvecs, gl)]
        configs = [("pgvector (ef_search=40, iterative_scan=off)", 40, "off"),
                   ("pgvector (ef_search=40, iterative_scan=relaxed_order)", 40, "relaxed_order"),
                   ("pgvector (ef_search=200, iterative_scan=off)", 200, "off")]
        for name, ef, it in configs:
            pg.mode("ann", ef=ef, iterative=it)
            res = [pg.search(v, g) for v, g in zip(qvecs, gl)]
            lat = statistics.median(timed(lambda v=v, g=g: pg.search(v, g)) for v, g in zip(qvecs, gl))
            section[name] = {"results_returned_mean": round(statistics.mean(len(r) for r in res), 2),
                             "queries_with_fewer_than_10": sum(len(r) < K for r in res),
                             "ANN_recall@10": round(statistics.mean(overlap(a, e) for a, e in zip(res, ref_pg)), 4),
                             "latency_ms_median": round(lat, 2)}
        res = [qd.search(v, g) for v, g in zip(qvecs, gl)]
        lat = statistics.median(timed(lambda v=v, g=g: qd.search(v, g)) for v, g in zip(qvecs, gl))
        section[f"qdrant (hnsw_ef={QDRANT_HNSW_EF}, payload index on genre)"] = {
            "results_returned_mean": round(statistics.mean(len(r) for r in res), 2),
            "queries_with_fewer_than_10": sum(len(r) < K for r in res),
            "ANN_recall@10": round(statistics.mean(overlap(a, e) for a, e in zip(res, ref_qd)), 4),
            "latency_ms_median": round(lat, 2)}
        out["D_filter"][style] = section
    pg.mode("ann")
    out["settings"]["pgvector plan (ANN, filtered)"] = pg.plan(qvecs[0], genres[0])

    # ---- E: one query joined with the business table ----
    text = "easy recipes for bread, cakes and pastries at home"
    v = recommend.text_to_vec(text)
    a = recommend.similar_pgvector_joined(v, "cookery")
    b = recommend.similar_qdrant_then_pg(v, "cookery")
    out["E_joined_query"] = {
        "question": f"5 most similar books to '{text}' in genre 'cookery' that can be borrowed right now",
        "pgvector (1 SQL statement)": [(r[0], r[1], r[2], round(float(r[3]), 4)) for r in a],
        "qdrant + PostgreSQL (2 steps)": [(r[0], r[1], r[2], round(float(r[3]), 4)) for r in b],
        "same_ids": [r[0] for r in a] == [r[0] for r in b],
    }
    return out
