# Library Loan Service – five databases, one decision

A small program that decides whether a library loan is **APPROVED / WAITLISTED / REJECTED** and
suggests alternatives, using PostgreSQL, MongoDB, Redis, Neo4j and a vector store (built twice:
pgvector and Qdrant). Start with [PLAN.md](PLAN.md) (the idea), then [NOTES.md](NOTES.md)
(explanations for the defence), then [report/REPORT.md](report/REPORT.md) (results).

## Run it (Windows, Docker Desktop, Python 3.13)

```bash
docker compose up -d                       # 1. start the 5 databases (wait ~20 s)
py -m venv .venv                           # 2. one-time Python setup
.venv/Scripts/python -m pip install -r requirements.txt
# 3. (optional) data is already committed. To rebuild it:
.venv/Scripts/python -m bookloan.fetch_openlibrary   # downloads the real books (~15 min, needs internet)
.venv/Scripts/python -m bookloan.datagen             # adds synthetic members/loans/stock
.venv/Scripts/python -m bookloan.run_all   # 4. load everything, run every test + measurement
```

`run_all` prints every number and saves them to `results/results.json`. The first run downloads the
embedding model (~90 MB). Ports used: PostgreSQL 5433, MongoDB 27017, Redis 6379, Neo4j 7687/7474, Qdrant 6333/6334.

## Folder map

| Path | What it is |
|---|---|
| `docker-compose.yml` | the five servers, pinned image versions |
| `sql/schema.sql` | PostgreSQL tables, constraints, `book_embeddings` (pgvector) |
| `bookloan/fetch_openlibrary.py` | downloads the real catalogue from Open Library → `data/openlibrary_books.json` |
| `bookloan/datagen.py` | builds `data/*.json`; adds the synthetic members, loans, stock (seed 42) |
| `data/README.md` | **which data is real and which is synthetic** |
| `bookloan/mongo_schema.py` | MongoDB `$jsonSchema` validator (fiction vs nonfiction) |
| `bookloan/load_all.py` | loads all five stores |
| `bookloan/decision.py` | **the decision**: rules, transaction, Redis cache |
| `bookloan/recommend.py` | alternatives from the graph and from vectors |
| `bookloan/refresh.py` | find and fix stale derived copies |
| `bookloan/experiments.py`, `vector_bench.py` | all measurements |
| `tests/` | labelled test cases (written before the code) |
| `results/` | printed output of the last run |

## Quick try by hand

```bash
.venv/Scripts/python -c "from bookloan.decision import preview_decision as p; print(p(9001,'B0004'), p(9002,'B0001'))"
```
