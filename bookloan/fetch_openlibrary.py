"""Download REAL catalogue data from Open Library (https://openlibrary.org, open data API).

For each of 21 subjects we take the most widely published books (sorted by Open Library rating) that have a
real English description, until we have 20 per subject = 420 books. We keep: title, author, description,
subjects, people/places the book is about, first publication year, page count, ISBN, and the Open Library key
(the source id). The result is saved to data/openlibrary_books.json so that everything else runs offline.

Run once (takes a few minutes, ~1000 polite requests):   python -m bookloan.fetch_openlibrary
Licence: Open Library catalogue data is available under CC0 / open licences (see data/README.md).
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .config import DATA_DIR

HEADERS = {"User-Agent": "DMI2026-student-project (botond.liko@gmail.com)"}
PER_GENRE = 20

# our genre label -> (Open Library subject, kind, keywords).
# Open Library subject tags are crowd-sourced and noisy (famous novels carry dozens of tags), so a book is only
# accepted when its title/description ALSO contains at least one keyword typical of the genre. Simple, visible, reproducible.
GENRES = {
    "detective fiction":   ("detective and mystery stories", "fiction", "murder detective mystery crime investigat sleuth clue inspector"),
    "thriller":            ("thriller", "fiction", "thriller killer conspiracy spy agent terror assassin chase danger suspense"),
    "science fiction":     ("science fiction", "fiction", "space alien planet future robot galaxy time machine starship"),
    "fantasy":             ("fantasy", "fiction", "magic wizard dragon kingdom sword quest elf witch"),
    "historical fiction":  ("historical fiction", "fiction", "war century king queen empire revolution historical england france rome"),
    "romance":             ("love stories", "fiction", "love romance marriage passion heart affair lover"),
    "horror":              ("horror", "fiction", "horror haunt ghost monster terror evil vampire nightmare supernatural"),
    "young adult":         ("young adult fiction", "fiction", "teen school girl boy friend growing sixteen high school"),
    "children's adventure": ("adventure stories", "fiction", "adventure journey island treasure children boys girls voyage"),
    "graphic novel":       ("graphic novels", "fiction", "graphic comic illustrat panel cartoon superhero drawn"),
    "poetry":              ("poetry", "fiction", "poem poet poetry verse sonnet lyric"),
    "biography":           ("biography", "nonfiction", "life biography born memoir career story of his her"),
    "travel writing":      ("voyages and travels", "nonfiction", "travel journey trip voyage expedition country walk road"),
    "cookery":             ("cooking", "nonfiction", "recipe cook food kitchen chef meal eat"),
    "self-help":           ("self-help", "nonfiction", "success habit mind confidence personal improve advice life change"),
    "popular science":     ("popular works", "nonfiction", "science universe scientist physics evolution brain nature theory"),
    "true crime":          ("true crime", "nonfiction", "murder crime killer trial case police true investigation"),
    "war history":         ("world war, 1939-1945", "nonfiction", "war battle soldier army wwii nazi military allied"),
    "philosophy":          ("philosophy", "nonfiction", "philosoph truth ethics reason knowledge moral thought"),
    "technology":          ("computer programming", "nonfiction", "program software code computer language algorithm"),
    "gardening":           ("gardening", "nonfiction", "garden plant grow flower soil vegetable"),
}

CACHE_FILE = DATA_DIR / ".ol_cache.json"        # local download cache (not committed)
_cache = {}


def get(url, tries=4):
    if url in _cache:
        return _cache[url]
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            _cache[url] = json.load(urllib.request.urlopen(req, timeout=30))
            time.sleep(0.15)                                  # be polite to the free API
            return _cache[url]
        except Exception:
            time.sleep(2 * (n + 1))
    return None


ENGLISH_WORDS = set("the a an and of to in is was his her he she it that with for as on by this who from at are be or their "
                    "they which but one not has had have its into when while after about more".split())


def clean_description(d):
    if isinstance(d, dict):
        d = d.get("value", "")
    if not isinstance(d, str):
        return None
    d = html.unescape(re.sub(r"<[^>]+>", " ", d))              # some descriptions contain HTML
    d = d.split("----------")[0]                              # Open Library appends "see also" blocks after this line
    d = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", d)           # markdown links -> their text
    d = re.sub(r"\[\d+\]:\s*\S+", "", d)                     # footnote definitions
    d = re.sub(r"[*_`#>]+", "", d)
    d = re.sub(r"\s+", " ", d).strip()
    if len(d) < 120:
        return None
    if "�" in d or "<" in d or sum(c.isascii() for c in d) / len(d) < 0.97:   # garbled / non-English text
        return None
    words = re.findall(r"[a-z']+", d.lower())
    if sum(w in ENGLISH_WORDS for w in words) < 0.12 * len(words):   # not English (Italian, Spanish, ... pass the ASCII test)
        return None
    if len(d) > 700:                                          # cut at a sentence end
        cut = d[:700]
        d = cut[:cut.rfind(". ") + 1] if ". " in cut[300:] else cut
    return d


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def main():
    if CACHE_FILE.exists():
        _cache.update(json.loads(CACHE_FILE.read_text(encoding="utf-8")))
    books, seen_titles, seen_keys = [], set(), set()
    for genre, (subject, kind, words) in GENRES.items():
        keywords = words.split()
        q = urllib.parse.urlencode({
            "q": f'subject:"{subject}" language:eng', "sort": "rating", "limit": 200,
            "fields": "key,title,author_name,first_publish_year,number_of_pages_median,isbn,edition_count"})
        res = get(f"https://openlibrary.org/search.json?{q}")
        got = 0
        for doc in (res or {}).get("docs", []):
            if got >= PER_GENRE:
                break
            key, title = doc["key"], doc["title"]
            if key in seen_keys or norm(title) in seen_titles or not doc.get("author_name"):
                continue
            if sum(c.isascii() for c in title) < 0.9 * len(title):        # non-Latin titles
                continue
            work = get(f"https://openlibrary.org{key}.json")
            desc = clean_description(work.get("description")) if work else None
            if not desc:
                continue
            if not any(k in (title + " " + desc).lower() for k in keywords):   # genre sanity check
                continue
            isbns = [i for i in doc.get("isbn", []) if len(i) == 13 and i.isdigit()]
            books.append({
                "ol_key": key, "title": title, "author": doc["author_name"][0], "genre": genre, "kind": kind,
                "ol_subject_used": subject, "description": desc,
                "subjects": [s for s in work.get("subjects", [])][:8],
                "subject_people": work.get("subject_people", [])[:8],
                "subject_places": work.get("subject_places", [])[:8],
                "first_publish_year": doc.get("first_publish_year"),
                "pages": doc.get("number_of_pages_median"),
                "isbn": isbns[0] if isbns else None,
                "edition_count": doc.get("edition_count"),
            })
            seen_keys.add(key)
            seen_titles.add(norm(title))
            got += 1
        print(f"{genre:22s} {got}/{PER_GENRE}", flush=True)
        CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")
    DATA_DIR.mkdir(exist_ok=True)
    out = {"source": "Open Library (openlibrary.org) search + works API",
           "retrieved_at": datetime.now(timezone.utc).isoformat(), "books": books}
    (DATA_DIR / "openlibrary_books.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("total books:", len(books))


if __name__ == "__main__":
    main()
