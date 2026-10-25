# Plan: Library Loan Service

## The idea in one paragraph
A public library decides, for each **loan request** ("member M wants book B"), one of three things:
**APPROVED**, **WAITLISTED** (no copy left) or **REJECTED** (a rule is broken: suspended, unpaid fines,
too many loans, too young for the book, ...). When the answer is not "approved", the service suggests
**alternatives**: other books by the same author, what other readers borrowed, and books with a
similar description that are available right now.

I chose it because everybody understands a library, the rules are small enough to explain in one
minute, and every one of the five database types has a natural job.

## Which store does what (the one-sentence reasons)

| Store | Holds | Why *here* |
|---|---|---|
| **PostgreSQL** | members, books (stock), loans, loan requests, decisions | Lending needs transactions, foreign keys and `CHECK` constraints: stock must never go negative, two people must not get the last copy. |
| **MongoDB** | the book catalogue record (description, age rating, subjects, fiction/nonfiction-specific fields) | Real catalogue records are irregular: fiction lists the *characters* it is about, nonfiction the *places*; pages / ISBN / year are often missing. A validated document fits better than a table full of empty columns. |
| **Redis** | cached decisions `loan:{member}:{book}:decision` with a 5-minute TTL | The same question is asked again and again; a key-value lookup is much faster than re-running the rules, and old entries should expire by themselves. |
| **Neo4j** | Book → Author, Book → Subject, Member → Book ("borrowed") | "Same author", "shares subjects", "readers who also borrowed" are relationship walks, which are one short query in a graph and several joins in SQL. |
| **pgvector** + **Qdrant** | embeddings of book descriptions, genre as metadata | "Books *like* this one" is a similarity question, not an exact match. Built twice on purpose, so the two can be compared. |

Rule of the setup: **PostgreSQL and MongoDB are the sources of truth. Redis, Neo4j, pgvector and
Qdrant only hold *derived* copies** (each remembers the source id and when it was refreshed).

## Steps (and where each one lives)

1. `docker-compose.yml` – one command starts all five servers, versions pinned.
2. `bookloan/fetch_openlibrary.py` – download **420 real books** from Open Library; `bookloan/datagen.py` – add the synthetic parts (members, loans, stock, age policy).
3. `tests/*.json` – test cases and labels, **written before** the decision code and before any tuning.
4. `sql/schema.sql`, `bookloan/mongo_schema.py`, `bookloan/load_all.py` – schemas and loaders.
5. `bookloan/decision.py` – the rules, the transaction, the Redis cache.
6. `bookloan/recommend.py` – graph and vector alternatives, and the "one SQL vs two steps" query.
7. `bookloan/refresh.py` – detect and repair stale derived copies.
8. `bookloan/experiments.py`, `bookloan/vector_bench.py` – every measurement.
9. `bookloan/run_all.py` – reloads everything, runs everything, writes `results/results.json`.
10. `report/REPORT.md` – the short report built from those printed numbers.

## What "done" means (checklist from the assignment)

- [x] one `docker compose up` for 5 stores, pinned versions
- [x] 200–1000 records per store, source noted (see NOTES.md for the honest exceptions)
- [x] PostgreSQL transaction + constraint; MongoDB `$jsonSchema` rejection; Redis cache-aside + stale demo
- [x] Neo4j queries; pgvector **and** Qdrant with the same vectors
- [x] ANN recall@10, shared ids, 5 % filter results/recall/latency, ef_search / iterative scan / hnsw_ef recorded
- [x] one query joined with business tables, in both systems
- [x] one update across stores (what goes stale, then refresh)
- [x] tests written before tuning; all numbers printed by the code
- [x] one failure case explained (REPORT.md)
