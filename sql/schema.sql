-- PostgreSQL = system of record for the BUSINESS entities and DECISIONS.
-- (Reason: loans and stock need transactions, constraints and joins.)
DROP TABLE IF EXISTS book_embeddings, decisions, loan_requests, loans, books, members CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE members (
    member_id   INT PRIMARY KEY,
    name        TEXT NOT NULL,
    birth_date  DATE NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('active', 'suspended')),
    fines_eur   NUMERIC(6,2) NOT NULL DEFAULT 0 CHECK (fines_eur >= 0)
);

-- Only the business facts about a book live here (stock, title). The flexible catalogue
-- record (description, format-specific fields, age rating) lives in MongoDB.
CREATE TABLE books (
    book_id           TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    genre             TEXT NOT NULL,
    copies_total      INT  NOT NULL CHECK (copies_total >= 1),
    copies_available  INT  NOT NULL,
    CHECK (copies_available >= 0 AND copies_available <= copies_total)   -- stock can never go negative
);

CREATE TABLE loans (
    loan_id     SERIAL PRIMARY KEY,
    member_id   INT  NOT NULL REFERENCES members(member_id),
    book_id     TEXT NOT NULL REFERENCES books(book_id),
    loaned_at   DATE NOT NULL,
    due_at      DATE NOT NULL,
    returned_at DATE
);
-- A member cannot hold the same book twice at the same time.
CREATE UNIQUE INDEX one_active_loan_per_book ON loans (member_id, book_id) WHERE returned_at IS NULL;

CREATE TABLE loan_requests (
    request_id   SERIAL PRIMARY KEY,
    member_id    INT  NOT NULL REFERENCES members(member_id),
    book_id      TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE decisions (
    decision_id SERIAL PRIMARY KEY,
    request_id  INT NOT NULL UNIQUE REFERENCES loan_requests(request_id),
    outcome     TEXT NOT NULL CHECK (outcome IN ('APPROVED', 'WAITLISTED', 'REJECTED')),
    reason_code TEXT NOT NULL,
    decided_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- DERIVED copy of the Mongo descriptions (pgvector). Keeps source id + refresh time.
CREATE TABLE book_embeddings (
    book_id      TEXT PRIMARY KEY REFERENCES books(book_id),   -- source id
    genre        TEXT NOT NULL,                                 -- metadata for filtering
    embedding    vector(384) NOT NULL,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
