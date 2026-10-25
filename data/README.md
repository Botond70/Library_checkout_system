# Data: what is real and what is not

| File | Content | Real? | Source |
|---|---|---|---|
| `openlibrary_books.json` | 420 books: title, author, description, subjects, characters/places, first publication year, page count, ISBN, Open Library key | **Real** | [Open Library](https://openlibrary.org) search + works API, downloaded by `bookloan/fetch_openlibrary.py` (the file records the download time). Open Library catalogue data is open (CC0 / public-domain dedication for metadata). |
| `books.json` | the 420 books in the shape loaded into MongoDB/PostgreSQL | real + 3 synthetic fields | adds `min_age` (library age policy per genre, an assumption), `copies_total`, `copies_available` (random stock) |
| `members.json` | 300 random members + 14 fixture members for the tests | **Synthetic** | `bookloan/datagen.py`, seed 42. Real borrower records are personal data and are not published. |
| `loans.json` | 920 loans (120 still active) | **Synthetic** | `bookloan/datagen.py` |

How the books were chosen: 21 Open Library subjects (one per genre label), the 20 most widely published books of each
(sorted by edition count) that have an English description of at least 120 characters; each book appears once.
Genre labels are the subject used to find the book, so they are authentic but noisy (Open Library subject tagging is crowd-sourced).
