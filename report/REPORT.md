# Report: Library Loan Service on five database types

All numbers below are printed by `python -m bookloan.run_all` and saved in `results/results.json`.

**Data.** The 420 books are **real**, downloaded from Open Library (title, author, description, subjects, pages, ISBN, source key).
Members (314), loans (920), copy counts and the age rating are **synthetic** (seed 42), because real borrower records are
personal data and Open Library has no stock or age policy. Details: `data/README.md`.

## 1. What the program decides
For a loan request (member, book) it returns **APPROVED / WAITLISTED / REJECTED** with a reason code, then
suggests alternatives. The first rule that fails decides: member exists, book exists, member active, fines ≤ 5.00 €, fewer than 3 active
loans, not already holding the book, age ≥ the book's `min_age` (from MongoDB), then a copy is available (APPROVED) or not (WAITLISTED).

## 2. Role of each store

| Store | Role | Records | One reason |
|---|---|---|---|
| PostgreSQL 16 | system of record: members, books/stock, loans, requests, decisions | 314 + 420 + 920 | transactions and constraints keep stock correct |
| MongoDB 7 | system of record: catalogue record per book | 420 | irregular real records (fiction: characters, nonfiction: places), validated by `$jsonSchema` |
| Redis 7.4 | derived: cached decision `loan:{m}:{b}:decision`, TTL 300 s | on demand | repeated question, automatic expiry |
| Neo4j 5.26 | derived: Book–Author, Book–Subject, Member–Book | 1,849 nodes, 2,594 edges | relationship walks |
| pgvector 0.8.0 | derived: description embeddings (384-d) | 420 | similarity search inside SQL |
| Qdrant 1.12.4 | derived: same embeddings | 420 | dedicated vector engine |

## 3. Main queries and what was shown

**Eligibility (PostgreSQL + MongoDB).** 19 labelled cases written before the code, including boundaries (fines exactly 5.00,
age by full DATE: turns 18 yesterday / today / tomorrow, 2 vs 3 active loans): **19 / 19 passed**. Age is the whole years between
a fixed reference date (2026-06-01) and the birth date.

**Transaction (PostgreSQL).** `request_loan` locks the book row (`SELECT … FOR UPDATE`), applies the rules, then inserts the
request, decision, loan and decrements stock in one transaction. Two members asking for the last copy at the same moment:
**one APPROVED, one WAITLISTED, copies left 0**. With the lock removed (and a 0.5 s pause to force the race) both passed the
check, but the `CHECK (copies_available >= 0)` constraint made the second write fail (`CheckViolation`) – the database
protected the data even when the application did not.

**Validation (MongoDB).** A fiction book without `subject_people`, a nonfiction book without `subject_places`, an unknown `kind`,
and a book without a title were each rejected with error code 121 (document validation); the collection stayed at 420 documents.

**Cache (Redis).** First read comes from the database, the second from Redis (TTL 300 s). After suspending a member *without*
touching Redis, the cache still answered APPROVED while the database answer was REJECTED/SUSPENDED (stale). Doing the same update with
the key deletion in the same function made the next read come from the database with the new answer.

**Graph (Neo4j).** For the waitlisted book B0002 the graph returned other books by the same author, books sharing subjects, and
"readers also borrowed" ids; one PostgreSQL query then kept only those with a free copy (6 of the returned ids were available).
Because loans are synthetic, "also borrowed" counts are all 1.

**Joined vector query.** "5 most similar books to *easy recipes for bread, cakes and pastries at home* in genre *cookery* that can be
borrowed now":
* pgvector – **one SQL statement**: `book_embeddings e JOIN books b … WHERE b.copies_available > 0 AND e.genre = … ORDER BY e.embedding <=> :q LIMIT 5`.
* Qdrant – **two steps**: ask Qdrant for 20 nearest ids (filter on genre), then a PostgreSQL query keeps those with stock.
* Both returned the same 5 books in the same order: *Joy of Cooking*, *On Food and Cooking*, *How to Cook Everything*,
  *Salt, Fat, Acid, Heat*, *The Art of Fermentation*.

## 4. Vector results (20 fixed queries, 420 real descriptions, k = 10)

| Measure | pgvector | Qdrant |
|---|---|---|
| ANN recall@10 vs own exact top-10 | 1.00 | 1.00 |
| Shared ids in the two top-10 sets (mean / min of 10) | 10 / 10 | 10 / 10 |
| Labelled recall@5 / MRR (label = genre) | 0.58 / 0.775 | 0.58 / 0.775 |
| Median latency, no filter | 0.73 ms | 7.55 ms REST, 1.95 ms gRPC |

Settings: pgvector `hnsw.ef_search = 40`, `hnsw.iterative_scan = off` (main runs), index `m=16, ef_construction=64`;
Qdrant `hnsw_ef = 64`, same `m` and `ef_construct`, payload index on `genre`. At 420 vectors both HNSW indexes are essentially
exact, so the two systems agree completely; this confirms they hold identical data but does not separate them.
Recall@5 / MRR are identical for the two systems because the vectors are identical; they are lower than a clean benchmark would give
because the genre labels come from crowd-sourced Open Library tags (a Harry Potter book is tagged as detective fiction, etc.).

**Filter keeping 4.8 % of rows (`genre = X`, 20 of 420).**

| Filter style | System / setting | Results returned (mean of 10) | ANN recall@10 | Median latency |
|---|---|---|---|---|
| filter matches the query's genre | pgvector ef_search 40, iterative off | 9.0 (8 queries < 10) | 0.90 | 0.76 ms |
| | pgvector ef_search 40, iterative `relaxed_order` | 10 | 1.00 | 0.80 ms |
| | pgvector ef_search 200, iterative off | 10 | 1.00 | 0.96 ms |
| | Qdrant hnsw_ef 64 + payload index (REST) | 10 | 1.00 | 5.3 ms |
| filter on an unrelated genre | pgvector ef_search 40, iterative off | **1.65** (20 queries < 10) | **0.165** | 0.79 ms |
| | pgvector ef_search 40, iterative `relaxed_order` | 10 | 1.00 | 1.11 ms |
| | pgvector ef_search 200, iterative off | 8.25 (8 queries < 10) | 0.825 | 1.06 ms |
| | Qdrant hnsw_ef 64 + payload index (REST) | 10 | 1.00 | 7.63 ms |

## 5. One update across stores
One MongoDB record (B0004, a Sherlock Holmes collection) was changed: `min_age` 0→16, a new description, a new author. Until
`refresh_book()` ran: Redis still said APPROVED for a 10-year-old (truth: REJECTED/AGE_RESTRICTED); both vector stores still ranked the
book 1st for the *old* text and did not find it for the *new* text; Neo4j still showed "Arthur Conan Doyle"; `find_stale()` listed B0004.
After the refresh: Redis key deleted (next read REJECTED from the database), the book ranks 1st for the new text in both vector stores and
not for the old one, the graph shows the corrected author, and no book is stale.

## 6. Failure case explained: filtered search in pgvector returns too few rows
**What happened.** With `WHERE genre = X` where X is unrelated to the query, pgvector (default settings) returned on average
**1.65 rows instead of 10**, and ANN recall@10 fell to **0.165**; even when the filter matched the query's genre it returned fewer than 10
rows for 8 of 20 queries. The query plan shows why: an *Index Scan* on the HNSW index with `Order By` the distance and a separate
`Filter: genre = …`. The HNSW index hands back only `ef_search` (= 40) nearest candidates; the genre filter is applied **afterwards**.
Only 4.8 % of rows are in the genre, so most of the 40 nearest vectors belong to other genres and are thrown away – the query silently
returns too few results (no error).

**Why it is dangerous.** The result looks valid, just short, and a plain increase to `ef_search = 200` only partly helps (8.25 rows).

**What fixed it.** Turning on `hnsw.iterative_scan = relaxed_order` (pgvector ≥ 0.8) makes the index keep scanning until enough rows pass
the filter: 10 rows, recall 1.00, about 1 ms. Qdrant handles this with a payload index on the filtered field and filter-aware
HNSW traversal: 10 rows, recall 1.00 out of the box.

**Related honest findings:** (1) my first benchmark run showed perfect pgvector filtered results, caused by a cached prepared-statement
plan from the exact-search phase; (2) my first Open Library download gave wrong genres because of noisy tags, so I
rejected it and added a keyword check (see `data/README.md`). The numbers above come from the corrected code and data.

## 7. Limits of this study
420 vectors is small (unfiltered ANN recall 1.0 is expected); genre labels are noisy crowd-sourced tags; members and loans are synthetic;
latencies include client and transport overhead on one machine; fastembed's ONNX build of all-MiniLM-L6-v2 was used.
