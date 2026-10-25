"""Build the data files that are loaded into the databases.

REAL data   : the 420 books come from Open Library (data/openlibrary_books.json, downloaded by
              bookloan/fetch_openlibrary.py). Title, author, description, subjects, pages, ISBN are real.
SYNTHETIC   : members, loans, copy counts and the age rating `min_age`. Reason: real borrower records are
              personal data and are not published; Open Library has no stock or age policy.
              (Deterministic: random.seed(42).)

Output (data/):  books.json -> MongoDB + PostgreSQL,  members.json, loans.json -> PostgreSQL
Run:  python -m bookloan.datagen
"""
import json
import random
from datetime import timedelta

from .config import DATA_DIR, REFERENCE_DATE

random.seed(42)

# Library age policy (an assumption of this project, NOT from Open Library): minimum age per genre.
MIN_AGE = {"horror": 16, "thriller": 16, "true crime": 16, "war history": 12, "romance": 12}

FIRST = ["Alma", "Bruno", "Clara", "Dmitri", "Elena", "Felix", "Greta", "Hugo", "Iris", "Jonas", "Katya", "Leon",
         "Maya", "Nils", "Olga", "Pavel", "Quinn", "Rosa", "Simon", "Tessa", "Ulrich", "Vera", "Walter", "Xenia",
         "Yara", "Zoltan", "Anna", "Benedek", "Dora", "Emil", "Fanni", "Gabor", "Hanna", "Imre", "Judit", "Karoly"]
LAST = ["Varga", "Moreau", "Lindqvist", "Okafor", "Brandt", "Kovacs", "Haddad", "Petrov", "Delgado", "Novak",
        "Fischer", "Ibsen", "Marlowe", "Tanaka", "Quarry", "Weaver", "Ashby", "Duran", "Eklund", "Farkas",
        "Gallo", "Holm", "Ivanov", "Jansen", "Keller", "Lombardi", "Moravec", "Nagy", "Ostrov", "Perrin"]


def make_books():
    """Real Open Library records -> catalogue documents (Mongo shape). Id B0001.. in file order."""
    raw = json.loads((DATA_DIR / "openlibrary_books.json").read_text(encoding="utf-8"))["books"]
    books = []
    for n, r in enumerate(raw, start=1):
        doc = {
            "_id": f"B{n:04d}",
            "ol_key": r["ol_key"],                     # source id in Open Library
            "title": r["title"],
            "author": r["author"],
            "genre": r["genre"],
            "kind": r["kind"],                         # fiction | nonfiction  (decides which extra fields are required)
            "min_age": MIN_AGE.get(r["genre"], 0),
            "description": r["description"],
            "subjects": r["subjects"],
            "updated_at": "2026-01-01T00:00:00Z",
        }
        # fields that differ by kind (the reason this lives in MongoDB)
        if r["kind"] == "fiction":
            doc["subject_people"] = r["subject_people"]       # characters the book is about
        else:
            doc["subject_places"] = r["subject_places"]       # places the book is about
        for opt in ("first_publish_year", "pages", "isbn"):   # real but not always known
            if r.get(opt):
                doc[opt] = r[opt]
        books.append(doc)
    return books


def apply_fixture_books(books):
    """Fixed books the eligibility test cases refer to (tests/eligibility_cases.json).
    Returns {book_id: copies_total} overrides for the copy counts."""
    for b in books[:5]:
        b["min_age"] = 0
    books[0]["min_age"] = 18              # B0001: adults only
    return {"B0001": 3, "B0002": 1, "B0003": 1, "B0004": 3, "B0005": 2}


def years_ago(n):
    """Birth date of someone who turns n years old exactly on REFERENCE_DATE."""
    return REFERENCE_DATE.replace(year=REFERENCE_DATE.year - n)


def make_members():
    members = []
    for i in range(1, 301):
        members.append({
            "member_id": i,
            "name": f"{random.choice(FIRST)} {random.choice(LAST)}",
            "birth_date": (REFERENCE_DATE - timedelta(days=random.randint(6 * 365, 76 * 365))).isoformat(),
            "status": "suspended" if random.random() < 0.04 else "active",
            "fines_eur": random.choice([0, 0, 0, 0, 0, 0, 1.5, 2.0, 3.5, 7.0, 12.5]),
        })
    # Fixture members (used by tests/eligibility_cases.json). Birth dates are relative to REFERENCE_DATE.
    fx = [
        (9001, "Fixture Adult",       years_ago(35), "active",    0.00),
        (9002, "Fixture Child",       years_ago(10), "active",    0.00),
        (9003, "Fixture Suspended",   years_ago(40), "suspended", 0.00),
        (9004, "Fixture Fined",       years_ago(40), "active",    12.50),
        (9005, "Fixture FineLimit",   years_ago(40), "active",    5.00),   # boundary: exactly the limit
        (9006, "Fixture MaxLoans",    years_ago(40), "active",    0.00),   # 3 active loans
        (9007, "Fixture TwoLoans",    years_ago(40), "active",    0.00),   # 2 active loans
        (9008, "Fixture HasBook",     years_ago(40), "active",    0.00),   # already holds B0005
        (9009, "Fixture Age18",       years_ago(18), "active",    0.00),   # boundary: turned 18 exactly today
        (9010, "Fixture Age17",       years_ago(17), "active",    0.00),
        (9011, "Fixture SuspFined",   years_ago(40), "suspended", 9.00),
        (9013, "Fixture Turns18Tmrw", years_ago(18) + timedelta(days=1), "active", 0.00),   # 17 years, 364 days -> still 17
        (9014, "Fixture Turned18Yday", years_ago(18) - timedelta(days=1), "active", 0.00),  # 18 since yesterday
        (9012, "Fixture Racer",       years_ago(30), "active",    0.00),   # second user for the last-copy race
    ]
    for mid, name, born, st, fine in fx:
        members.append({"member_id": mid, "name": name, "birth_date": born.isoformat(), "status": st, "fines_eur": fine})
    return members


def make_loans(books, members, copies_total):
    """~800 historical (returned) loans + active loans; keeps copies_available consistent."""
    loans, active_per_book, active_per_member = [], {}, {}
    ids = [b["_id"] for b in books]
    regular = [m["member_id"] for m in members if m["member_id"] < 9000]
    today = REFERENCE_DATE

    def add(mid, bid, start, returned):
        due = start + timedelta(days=21)
        loans.append({"member_id": mid, "book_id": bid, "loaned_at": start.isoformat(), "due_at": due.isoformat(),
                      "returned_at": returned.isoformat() if returned else None})
        if not returned:
            active_per_book[bid] = active_per_book.get(bid, 0) + 1
            active_per_member[mid] = active_per_member.get(mid, 0) + 1

    # Fixture loans first
    add(9006, "B0010", today - timedelta(days=5), None)
    add(9006, "B0011", today - timedelta(days=4), None)
    add(9006, "B0012", today - timedelta(days=3), None)
    add(9007, "B0013", today - timedelta(days=5), None)
    add(9007, "B0014", today - timedelta(days=4), None)
    add(9008, "B0005", today - timedelta(days=2), None)
    # "B0002" has 1 copy and must be fully lent out -> a regular member holds it
    add(1, "B0002", today - timedelta(days=6), None)

    for _ in range(800):                                  # historical, returned loans
        mid, bid = random.choice(regular), random.choice(ids)
        start = today - timedelta(days=random.randint(30, 700))
        add(mid, bid, start, start + timedelta(days=random.randint(5, 30)))

    tries = 0                                             # more active loans (never exceeding copies or 2 per member)
    while sum(1 for l in loans if not l["returned_at"]) < 120 and tries < 5000:
        tries += 1
        mid, bid = random.choice(regular), random.choice(ids[10:])      # keep fixture books untouched
        if active_per_member.get(mid, 0) >= 2:
            continue
        if active_per_book.get(bid, 0) >= copies_total[bid] - 1:        # always leave 1 copy free
            continue
        if any(l["member_id"] == mid and l["book_id"] == bid and not l["returned_at"] for l in loans):
            continue
        add(mid, bid, today - timedelta(days=random.randint(1, 20)), None)
    return loans, active_per_book


def main():
    DATA_DIR.mkdir(exist_ok=True)
    books = make_books()
    overrides = apply_fixture_books(books)
    copies_total = {b["_id"]: random.randint(1, 4) for b in books}
    copies_total.update(overrides)
    members = make_members()
    loans, active_per_book = make_loans(books, members, copies_total)

    for b in books:
        b["copies_total"] = copies_total[b["_id"]]
        b["copies_available"] = copies_total[b["_id"]] - active_per_book.get(b["_id"], 0)
    assert books[1]["copies_available"] == 0          # B0002: no copies left (fixture)
    assert books[2]["copies_available"] == 1          # B0003: exactly one copy left (fixture)

    (DATA_DIR / "books.json").write_text(json.dumps(books, indent=1, ensure_ascii=False), encoding="utf-8")
    (DATA_DIR / "members.json").write_text(json.dumps(members, indent=1), encoding="utf-8")
    (DATA_DIR / "loans.json").write_text(json.dumps(loans, indent=1), encoding="utf-8")
    print(f"books={len(books)} members={len(members)} loans={len(loans)} "
          f"active_loans={sum(1 for l in loans if not l['returned_at'])}")


if __name__ == "__main__":
    main()
