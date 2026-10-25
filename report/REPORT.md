# Report: Library Loan Service on five database types

All numbers below are printed by `python -m bookloan.run_all` and saved in `results/results.json`.
Data is synthetic (seed 42): 420 books, 312 members, 920 loans.

## 1. What the program decides
For a loan request (member, book) it returns **APPROVED / WAITLISTED / REJECTED** with a reason code, then
suggests alternatives. Rules are listed in `NOTES.md` §1.

## 2. Role of each store

| Store | Role | Records | One reason |
|---|---|---|---|
| PostgreSQL 16 | system of record: members, books/stock, loans, requests, decisions | 312 + 420 + 920 | transactions and constraints keep stock correct |
| MongoDB 7 | system of record: catalogue record per book | 420 | fields differ per format, validated by `$jsonSchema` |
| Redis 7.4 | derived: cached decision `loan:{m}:{b}:decision`, TTL 300 s | on demand | repeated question, automatic expiry |
| Neo4j 5.26 | derived: Book–Author–Series–Member | 835 nodes, 1,547 edges | relationship walks |
| pgvector 0.8.0 | derived: description embeddings (384-d) | 420 | similarity search inside SQL |
| Qdrant 1.12.4 | derived: same embeddings | 420 | dedicated vector engine |

## 3. Main queries and what was shown

**Eligibility (PostgreSQL + MongoDB).** 17 labelled cases written before the code, including boundaries (fines exactly 5.00,
age exactly 18, 2 vs 3 active loans): **17 / 17 passed**.

**Transaction (PostgreSQL).** `request_loan` locks the book row (`SELECT … FOR UPDATE`), applies the rules, then inserts the
request, decision, loan and decrements stock in one transaction. Two members asking for the last copy at the same moment:
**one APPROVED, one WAITLISTED, copies left 0**. With the lock removed (and a 0.5 s pause to force the race) both passed the
check, but the `CHECK (copies_available >= 0)` constraint made the second write fail (`CheckViolation`) – the database
protected the data even when the application did not.

**Validation (MongoDB).** Inserting a novel without `pages`, an audiobook without `narrator`, or a graphic novel with the wrong
fields failed with error code 121 (document validation) each time; collection size stayed 420.

**Cache (Redis).** First read comes from the database, the second from Redis (TTL 300 s). After suspending a member *without*
touching Redis, the cache still answered APPROVED while the database answer was REJECTED/SUSPENDED (stale). Doing the same update with
the key deletion in the same function made the next read come from the database with the new answer.

**Graph (Neo4j).** For the waitlisted book B0002 the graph returned other books by the same author and "readers also
borrowed" ids; one PostgreSQL query then kept only the ones with a free copy (7 of the returned ids available now).

**Joined vector query.** "5 most similar books to *easy recipes for bread, cakes and pastries at home* in genre *cookery* that can be
borrowed now":
* pgvector – **one SQL statement**: `book_embeddings e JOIN books b … WHERE b.copies_available > 0 AND e.genre = … ORDER BY e.embedding <=> :q LIMIT 5`.
* Qdrant – **two steps**: ask Qdrant for 20 nearest ids (filter on genre), then a PostgreSQL query keeps those with stock.
* Both returned the same 5 ids in the same order (B0223, B0224, B0226, B0221, B0227).

## 4. Vector results (20 fixed queries, 420 vectors, k = 10)

| Measure | pgvector | Qdrant |
|---|---|---|
| ANN recall@10 vs own exact top-10 | 1.00 | 1.00 |
| Shared ids in the two top-10 sets (mean / min of 10) | 10 / 10 | 10 / 10 |
| Labelled recall@5 / MRR | 0.81 / 0.8725 | 0.81 / 0.8725 |
| Median latency, no filter | 0.67 ms | 15.6 ms REST, 1.79 ms gRPC |

Settings: pgvector `hnsw.ef_search = 40`, `hnsw.iterative_scan = off` (main runs), index `m=16, ef_construction=64`;
Qdrant `hnsw_ef = 64`, same `m` and `ef_construct`, payload index on `genre`. At 420 vectors both HNSW indexes are essentially
exact, so the two systems agree completely; this confirms they hold identical data but does not separate them.

**Filter keeping 4.8 % of rows (`genre = X`, 20 of 420).**

| Filter style | System / setting | Results returned (mean of 10) | ANN recall@10 | Median latency |
|---|---|---|---|---|
| filter matches the query's topic | pgvector ef_search 40, iterative off | 9.75 (2 queries < 10) | 0.975 | 0.87 ms |
| | pgvector ef_search 40, iterative `relaxed_order` | 10 | 1.00 | 0.70 ms |
| | pgvector ef_search 200, iterative off | 10 | 1.00 | 1.01 ms |
| | Qdrant hnsw_ef 64 + payload index (REST) | 10 | 1.00 | 15.3 ms |
| filter on an unrelated genre | pgvector ef_search 40, iterative off | **0.85** (20 queries < 10) | **0.085** | 0.73 ms |
| | pgvector ef_search 40, iterative `relaxed_order` | 10 | 1.00 | 1.08 ms |
| | pgvector ef_search 200, iterative off | 7.65 (12 queries < 10) | 0.765 | 1.05 ms |
| | Qdrant hnsw_ef 64 + payload index (REST) | 10 | 1.00 | 6.07 ms |

## 5. One update across stores
One MongoDB record (B0004) was changed: `min_age` 0→16, new description, new author. Until `refresh_book()` ran:
Redis still said APPROVED for a 10-year-old (truth: REJECTED/AGE_RESTRICTED); both vector stores still ranked the book 1st for
the *old* text and did not find it for the *new* text; Neo4j still showed the old author; `find_stale()` listed B0004. After the
refresh: Redis key deleted (next read REJECTED from the database), the book ranks 1st for the new text in both vector stores and
not for the old one, the graph shows the corrected author, and no book is stale.

## 6. Failure case explained: filtered search in pgvector returns almost nothing
**What happened.** With `WHERE genre = X` where X is unrelated to the query, pgvector (default settings) returned on average
**0.85 rows instead of 10**, and ANN recall@10 fell to **0.085**. The query plan shows why: an *Index Scan* on the HNSW index
with `Order By` the distance and a separate `Filter: genre = …`. The HNSW index hands back only `ef_search` (= 40) nearest
candidates; the genre filter is applied **afterwards**. Since only 4.8 % of rows are in the genre and the 40 nearest vectors belong to
other genres, almost all candidates are thrown away – the query silently returns too few results (no error).

**Why it is dangerous.** The result looks valid, just short, and a plain increase to `ef_search = 200` only partly helps (7.65 rows).

**What fixed it.** Turning on `hnsw.iterative_scan = relaxed_order` (pgvector ≥ 0.8) makes the index keep scanning until enough rows pass
the filter: 10 rows, recall 1.00, latency about 1 ms. Qdrant handles this with a payload index on the filtered field and filter-aware
HNSW traversal: 10 rows, recall 1.00 out of the box.

**Related honest finding:** my first benchmark run showed perfect pgvector filtered results, caused by a cached prepared-statement
plan from the exact-search phase (see `NOTES.md` §6). The numbers above are from the corrected code.

## 7. Limits of this study
420 vectors is small (ANN recall 1.0 is expected); labels come from the same generator that wrote the texts (optimistic quality);
latencies include client and transport overhead on one machine; fastembed's ONNX build of all-MiniLM-L6-v2 was used.
Full list: `NOTES.md` §8.
