"""Generate the synthetic library data (deterministic: random.seed(42)).

SOURCE OF DATA: fully synthetic, produced by this file. No public dataset was used, because
the project needs labelled ground truth (which books belong to the same "topic").
Each book belongs to one of 42 topics (21 genres x 2 sub-topics), 10 books per topic.
The topic is the ground truth for the vector-search labels in tests/vector_queries.json.

Output (all in data/):
  books.json     -> goes to MongoDB (system of record for the catalogue)
  members.json   -> PostgreSQL
  loans.json     -> PostgreSQL
Run:  python -m bookloan.datagen
"""
import json
import random
from datetime import date, timedelta

from .config import DATA_DIR, REFERENCE_YEAR

random.seed(42)

# (genre, topic_key, protagonists, settings, conflicts)
# Each topic has its own vocabulary, so books of one topic read alike (and different topics don't).
TOPICS = [
    ("cosy mystery", "village_murder",
     ["a retired schoolteacher", "the village baker", "a curious librarian"],
     ["a sleepy English village", "a seaside tea room town", "a village with a famous flower show"],
     ["investigates a poisoning at the annual fete", "solves the murder of the parish treasurer", "tracks down who stole the vicar's prize marrow"]),
    ("cosy mystery", "bookshop_secrets",
     ["a bookshop owner", "an antiquarian bookseller", "a widowed librarian"],
     ["a crooked old bookshop", "a university town's rare book market", "a lakeside book festival"],
     ["finds a coded letter hidden inside a first edition", "is drawn into the theft of a priceless manuscript", "uncovers why a customer vanished after buying one book"]),
    ("crime thriller", "serial_hunt",
     ["a burned-out detective", "a forensic profiler", "a rookie homicide inspector"],
     ["a rain-soaked port city", "the back streets of a northern industrial town", "a city gripped by a heatwave"],
     ["hunts a killer who leaves a chess piece at every scene", "races to stop a murderer who phones the police before each crime", "follows a trail of victims who all share one forgotten case"]),
    ("crime thriller", "heist",
     ["a retired safecracker", "a gifted forger", "a getaway driver"],
     ["a glittering casino", "a national art museum", "a diamond exchange"],
     ["plans one last robbery that goes wrong", "is blackmailed into stealing a painting", "must trust a crew of strangers to rob an unbeatable vault"]),
    ("science fiction", "generation_ship",
     ["a young engineer", "the ship's archivist", "a teenage navigator"],
     ["a generation ship centuries from Earth", "the sealed farming decks of a colony vessel", "a starship whose crew has forgotten its mission"],
     ["discovers the ship is drifting off course", "uncovers a mutiny planned by the founders' descendants", "learns the destination planet may no longer exist"]),
    ("science fiction", "first_contact",
     ["a linguist", "a radio astronomer", "a diplomat"],
     ["a research base under Antarctic ice", "an orbital listening station", "a quiet observatory in the desert"],
     ["tries to decode a signal from another star", "negotiates with a visitor that communicates only in colours", "must decide whether to answer a message from an alien civilisation"]),
    ("fantasy", "dragon_quest",
     ["a farm boy", "an exiled princess", "a young dragon-rider"],
     ["a kingdom of mountain citadels", "the ash-covered lands beyond the northern wall", "a realm where dragons sleep under the hills"],
     ["sets out to wake the last dragon", "must unite quarrelling kings against a dragon army", "bonds with a dragon egg that should never have hatched"]),
    ("fantasy", "magic_school",
     ["a scholarship student", "a shy apprentice mage", "a rebellious sorceress-in-training"],
     ["a floating academy of magic", "a tower school hidden in the clouds", "an ancient university built into a mountain"],
     ["discovers a forbidden spellbook in the restricted library", "is accused of a magical crime she did not commit", "competes in a deadly tournament between the houses"]),
    ("historical fiction", "wartime_home",
     ["a nurse", "a young mother", "a factory worker"],
     ["a bombed English city in 1941", "a French village under occupation", "a munitions factory in 1943"],
     ["hides a wounded soldier in the cellar", "keeps her family together while the front line moves closer", "carries secret messages for the resistance"]),
    ("historical fiction", "ancient_rome",
     ["a freed slave", "a young senator's daughter", "a gladiator-turned-teacher"],
     ["Rome under the emperors", "a Roman frontier fort in Britain", "the busy port of Ostia"],
     ["gets caught up in a conspiracy against the emperor", "tries to buy her family's freedom", "survives the great fire that engulfs the city"]),
    ("romance", "second_chance",
     ["a returning architect", "a widowed chef", "a small-town vet"],
     ["a lakeside hometown", "a Tuscan vineyard", "a snowy mountain inn"],
     ["meets the love she left behind years ago", "must work beside her former fiance to save the family business", "falls for the neighbour who once broke her heart"]),
    ("romance", "enemies_to_lovers",
     ["a rival chef", "an ambitious lawyer", "a feuding rival editor"],
     ["two competing restaurants on one street", "a high-stakes law firm", "a struggling publishing house"],
     ["is forced to share a project with her greatest rival", "bets her rival that she can win the contract first", "slowly discovers the enemy she hates is her perfect match"]),
    ("horror", "haunted_house",
     ["a newlywed couple", "a skeptical paranormal investigator", "a lonely caretaker"],
     ["an isolated Victorian mansion", "a crumbling manor on the moors", "an abandoned boarding house"],
     ["hears whispers inside the walls at night", "finds that the house remembers every family that died there", "cannot leave once the doors lock themselves"]),
    ("horror", "cursed_village",
     ["a visiting folklorist", "a stranded traveller", "a priest's niece"],
     ["a fog-bound fishing village", "a remote mountain hamlet", "an island cut off by winter storms"],
     ["learns the villagers make a sacrifice each midwinter", "wakes something old beneath the church", "realises the locals are not what they seem"]),
    ("young adult", "dystopia",
     ["a sixteen-year-old rebel", "a girl chosen by lottery", "a boy who forges ration cards"],
     ["a walled city ruled by a council", "a future nation divided into districts", "a world where emotions are medicated"],
     ["joins an underground movement against the regime", "volunteers to take her sister's place in the games", "discovers the truth behind the city's walls"]),
    ("young adult", "coming_of_age",
     ["a quiet new student", "a teenage poet", "a girl who moves in with her grandmother"],
     ["a small coastal town in summer", "a crowded high school", "a seaside caravan park"],
     ["finds friendship and first love over one summer", "learns to speak up after a family secret comes out", "discovers who she wants to be after leaving her old friends behind"]),
    ("children's adventure", "animal_friends",
     ["a brave hedgehog", "a clumsy young fox", "a talkative parrot"],
     ["a magical forest", "a riverbank full of busy animals", "an old farm with a secret orchard"],
     ["sets off to find the lost golden acorn", "leads his friends to rescue the river from a grumpy beaver", "learns that being different is a strength"]),
    ("children's adventure", "treasure_map",
     ["twin siblings", "three curious cousins", "a boy and his dog"],
     ["a grandfather's old lighthouse", "a seaside cave full of echoes", "a small island over the summer holidays"],
     ["follow a pirate's map hidden in the attic", "crack riddles to find the missing treasure", "outwit the sneaky neighbour hunting the same gold"]),
    ("biography", "scientist_life",
     ["a pioneering chemist", "a self-taught astronomer", "a pioneering woman physicist"],
     ["a cramped laboratory in the nineteenth century", "the early years of modern physics", "a university that refused to admit women"],
     ["struggles for recognition against a sceptical establishment", "makes a discovery that changes science forever", "balances family duty with groundbreaking research"]),
    ("biography", "explorer_life",
     ["a polar explorer", "a mountain climber", "an ocean sailor"],
     ["the frozen Antarctic", "the slopes of the Himalayas", "the open Atlantic in a tiny boat"],
     ["pushes human endurance beyond all limits", "leads a doomed expedition", "returns home a changed person after years away"]),
    ("travel writing", "walking_trip",
     ["a middle-aged writer", "a pair of old friends", "a solo hiker"],
     ["the pilgrim path across northern Spain", "the coastal trails of Cornwall", "the long ridges of the Scottish Highlands"],
     ["walks hundreds of miles to understand grief", "discovers local food and hospitality step by step", "meets strangers who change the journey"]),
    ("travel writing", "city_portrait",
     ["a long-term resident", "a curious foreign correspondent", "a food-loving traveller"],
     ["the markets and alleys of Istanbul", "the neon streets of Tokyo", "the canals and cafes of Amsterdam"],
     ["explores a city through its street food", "tells the hidden history behind famous landmarks", "describes a year of learning to belong in a new place"]),
    ("cookery", "baking",
     ["a home baker", "a pastry chef", "a bread obsessive"],
     ["a warm family kitchen", "a small village bakery", "a Parisian patisserie"],
     ["shares recipes for sourdough, cakes and pastry", "explains the science behind perfect bread", "offers simple bakes for beginners with step-by-step photos"]),
    ("cookery", "quick_dinners",
     ["a busy parent", "a student cook", "a food blogger"],
     ["a tiny apartment kitchen", "a weeknight at home", "a budget-friendly pantry"],
     ["presents thirty-minute vegetarian dinners", "collects one-pan meals that need almost no washing up", "shows how to eat well cheaply with seven ingredients"]),
    ("self-help", "habits",
     ["a productivity coach", "a behavioural psychologist", "a former burnout survivor"],
     ["the modern office", "a cluttered home desk", "the first hour of every morning"],
     ["explains how small daily habits compound over time", "teaches how to beat procrastination and focus deeply", "shows how to build a routine that actually lasts"]),
    ("self-help", "mindfulness",
     ["a meditation teacher", "a hospital psychologist", "a retired monk"],
     ["a quiet retreat centre", "a stressful city life", "a daily ten-minute practice"],
     ["introduces mindfulness exercises for anxiety", "shows how to sleep better and worry less", "guides readers through breathing, gratitude and acceptance"]),
    ("popular science", "space_cosmos",
     ["an astrophysicist", "a planetary scientist", "a science communicator"],
     ["the edge of the observable universe", "the surface of Mars", "the heart of a black hole"],
     ["explains how stars, galaxies and black holes were formed", "tells the story of the search for life on other planets", "describes the first second of the universe in plain language"]),
    ("popular science", "human_brain",
     ["a neuroscientist", "a sleep researcher", "a cognitive psychologist"],
     ["the laboratory and the clinic", "a dreaming mind at night", "the everyday decisions we make"],
     ["explores how memory is built and lost", "reveals what happens in the brain while we sleep", "shows why intuition fools us"]),
    ("true crime", "cold_case",
     ["a retired detective", "an investigative journalist", "a cold-case volunteer"],
     ["a small town haunted by an old murder", "a city archive of unsolved files", "a quiet suburb where a girl vanished in 1987"],
     ["reopens a decades-old murder with new DNA evidence", "reconstructs a disappearance that police abandoned", "exposes mistakes that put an innocent man in prison"]),
    ("true crime", "financial_fraud",
     ["a whistleblower accountant", "a financial reporter", "a fraud investigator"],
     ["a collapsing investment firm", "a glossy startup built on lies", "a bank that hid billions in losses"],
     ["exposes a pyramid scheme that ruined thousands", "follows the money behind a spectacular corporate collapse", "tells how a charming con artist fooled an entire industry"]),
    ("war history", "world_war_two",
     ["an infantry soldier", "a bomber pilot", "a codebreaker"],
     ["the beaches of Normandy", "the skies over Germany", "a secret codebreaking hut"],
     ["recounts the D-Day landings from the soldiers' view", "describes the air war through letters home", "tells how breaking an enemy cipher changed the course of the war"]),
    ("war history", "ancient_battles",
     ["a military historian", "a classical scholar", "a battlefield archaeologist"],
     ["the plains of Marathon", "the walls of Troy", "the Alps crossed by elephants"],
     ["analyses the great battles of the ancient world", "reconstructs a legendary siege from archaeology", "follows Hannibal's march on Rome"]),
    ("poetry", "nature_verse",
     ["a rural poet", "a quiet observer of birds", "a coastal wanderer"],
     ["fields, hedges and rivers", "an autumn woodland", "tide pools and salt marsh"],
     ["collects short poems about the changing seasons", "celebrates wildlife and the passing of time", "writes about solitude and wide open skies"]),
    ("poetry", "love_verse",
     ["a young lyricist", "a widower", "a city dweller in love"],
     ["late-night cafes", "letters left unsent", "a first apartment together"],
     ["gathers sonnets about love and loss", "writes tender poems for a missing partner", "captures the thrill and ache of falling in love"]),
    ("graphic novel", "superheroes",
     ["a teenage hero", "a masked vigilante", "a retired super-soldier"],
     ["a neon megacity", "a rooftop-lined metropolis", "a secret hero academy"],
     ["fights a villain who steals people's powers", "struggles to keep a double life secret", "must save the city from a rogue AI"]),
    ("graphic novel", "memoir_comics",
     ["an illustrator", "a child of immigrants", "a young cartoonist"],
     ["a crowded family flat", "a school in a new country", "a small studio apartment"],
     ["tells her family history in drawings", "draws what it feels like to grow up between two cultures", "captures an awkward teenage year in funny panels"]),
    ("philosophy", "ethics",
     ["a moral philosopher", "a university lecturer", "a thoughtful essayist"],
     ["a seminar room", "the dilemmas of daily life", "the ancient Greek agora"],
     ["asks what we owe to strangers", "explains the big ethical theories through thought experiments", "debates whether free will exists"]),
    ("philosophy", "stoicism",
     ["a modern Stoic", "a classics professor", "a counsellor"],
     ["the letters of Seneca", "the notebook of Marcus Aurelius", "an ordinary stressful day"],
     ["applies ancient Stoic advice to modern anxiety", "shows how to stay calm when events are out of control", "interprets short daily meditations on virtue and duty"]),
    ("technology", "programming",
     ["a veteran software engineer", "a computer science teacher", "an open-source maintainer"],
     ["the world of web development", "a growing codebase", "a first programming course"],
     ["teaches clean code and sound software design", "explains how to learn programming from scratch", "shows how databases and distributed systems really work"]),
    ("technology", "ai_future",
     ["a machine-learning researcher", "a tech journalist", "an ethicist"],
     ["the labs building artificial intelligence", "an economy transformed by automation", "a near future full of smart machines"],
     ["explains how neural networks learn", "asks whether artificial intelligence will take our jobs", "weighs the risks and promises of super-intelligent machines"]),
    ("gardening", "vegetable_garden",
     ["an allotment holder", "a first-time grower", "an organic gardener"],
     ["a small backyard plot", "a sunny raised bed", "a damp allotment"],
     ["explains how to grow tomatoes, beans and potatoes", "shows month by month what to sow and harvest", "teaches composting and natural pest control"]),
    ("gardening", "wild_garden",
     ["a wildlife gardener", "a meadow enthusiast", "a pond builder"],
     ["a front garden full of weeds", "a wildflower meadow", "a garden pond alive with frogs"],
     ["shows how to attract bees, birds and butterflies", "explains how to turn a lawn into a meadow", "argues for a messier, wilder garden"]),
]

assert len(TOPICS) == 42

EXTRA = [
    "A page-turner with a strong sense of place.",
    "Warm, clever and easy to read.",
    "Praised by critics for its vivid detail.",
    "A long-awaited new release.",
    "A book readers will want to share.",
    "Thoughtful, sharp and surprisingly moving.",
    "Perfect for a rainy weekend.",
    "The author's most accessible work yet.",
]

FIRST = ["Alma", "Bruno", "Clara", "Dmitri", "Elena", "Felix", "Greta", "Hugo", "Iris", "Jonas", "Katya", "Leon",
         "Maya", "Nils", "Olga", "Pavel", "Quinn", "Rosa", "Simon", "Tessa", "Ulrich", "Vera", "Walter", "Xenia",
         "Yara", "Zoltan", "Anna", "Benedek", "Dora", "Emil", "Fanni", "Gabor", "Hanna", "Imre", "Judit", "Karoly"]
LAST = ["Varga", "Moreau", "Lindqvist", "Okafor", "Brandt", "Kovacs", "Haddad", "Petrov", "Delgado", "Novak",
        "Fischer", "Ibsen", "Marlowe", "Tanaka", "Quarry", "Weaver", "Ashby", "Duran", "Eklund", "Farkas",
        "Gallo", "Holm", "Ivanov", "Jansen", "Keller", "Lombardi", "Moravec", "Nagy", "Ostrov", "Perrin"]
TITLE_ADJ = ["Silent", "Last", "Hidden", "Golden", "Broken", "Crimson", "Quiet", "Forgotten", "Midnight", "Distant",
             "Hollow", "Bright", "Secret", "Winter", "Restless", "Paper", "Iron", "Salt", "Velvet", "Wandering", "Amber", "Fading", "Northern", "Sunken", "Gentle", "Wild", "Narrow", "Burning", "Lost", "Tender"]
TITLE_NOUN = ["Garden", "Lighthouse", "Letter", "Harbour", "Orchard", "Signal", "Compass", "Season", "Door", "River",
              "Tower", "Promise", "Map", "Window", "Echo", "Bridge", "Lantern", "Road", "Shadow", "Key", "Garden Wall", "Clock", "Tide", "Fire", "Island", "Mirror", "Stair", "Song", "Field", "Crossing"]
FIRST_NAMES_M = ["Ava", "Ben", "Cal", "Dana", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jess", "Kai", "Lena", "Max", "Noor",
                 "Otto", "Pia", "Ravi", "Sam", "Tara", "Uma"]

FORMATS = ["novel", "audiobook", "graphic_novel"]
# Age restrictions per genre (min_age); everything not listed is open to all ages.
MIN_AGE = {"horror": 16, "crime thriller": 16, "true crime": 16, "war history": 12, "romance": 12}


def make_books():
    """420 books = 42 topics x 10; every topic is written by 2 authors (5 books each)."""
    books, used_titles = [], set()
    n = 0
    authors = []                       # (name) 84 unique authors
    names = [f"{f} {l}" for f in FIRST for l in LAST]
    random.shuffle(names)
    for t_idx, (genre, topic, prots, sets, confs) in enumerate(TOPICS):
        for a in range(2):
            author = names[t_idx * 2 + a]
            authors.append(author)
            # the author with a == 0 writes a numbered series; the other one writes stand-alone books
            series = f"The {author.split()[1]} {topic.replace('_', ' ').title()} Series" if a == 0 else None
            for k in range(5):
                n += 1
                while True:
                    title = f"The {random.choice(TITLE_ADJ)} {random.choice(TITLE_NOUN)}"
                    if title not in used_titles:
                        used_titles.add(title)
                        break
                p, s, c = random.choice(prots), random.choice(sets), random.choice(confs)
                tmpl = random.choice([
                    "In {s}, {p} {c}.",
                    "{P} {c}. The story unfolds in {s}.",
                    "Set in {s}: {p} {c}.",
                ])
                desc = tmpl.format(p=p, P=p[0].upper() + p[1:], s=s, c=c) + " " + random.choice(EXTRA)
                fmt = random.choices(FORMATS, weights=[6, 2, 2] if genre != "graphic novel" else [0, 0, 1])[0]
                doc = {
                    "_id": f"B{n:04d}",
                    "title": title,
                    "author": author,
                    "genre": genre,
                    "topic": topic,                      # ground truth for vector labels
                    "format": fmt,
                    "min_age": MIN_AGE.get(genre, 0),
                    "description": desc,
                    "tags": [genre.split()[0], topic.split("_")[0]],
                    "series": series,
                    "series_position": (k + 1) if series else None,
                    "updated_at": "2026-01-01T00:00:00Z",
                }
                # fields that differ per format (the reason this lives in MongoDB)
                if fmt == "novel":
                    doc.update(pages=random.randint(120, 640), isbn=f"978-{random.randint(10**9, 10**10 - 1)}")
                elif fmt == "audiobook":
                    doc.update(duration_minutes=random.randint(120, 900), narrator=random.choice(FIRST) + " " + random.choice(LAST))
                else:
                    doc.update(artist=random.choice(FIRST) + " " + random.choice(LAST), issue_number=random.randint(1, 12))
                books.append(doc)
    return books


def apply_fixture_books(books):
    """Fixed books the eligibility test cases refer to (tests/eligibility_cases.json).
    Returns {book_id: copies_total} overrides for the copy counts."""
    by_id = {b["_id"]: b for b in books}
    by_id["B0001"]["min_age"] = 18        # adults only
    by_id["B0002"]["min_age"] = 0
    by_id["B0003"]["min_age"] = 0
    by_id["B0004"]["min_age"] = 0
    by_id["B0005"]["min_age"] = 0
    return {"B0001": 3, "B0002": 1, "B0003": 1, "B0004": 3, "B0005": 2}


def make_members():
    members = []
    for i in range(1, 301):
        members.append({
            "member_id": i,
            "name": f"{random.choice(FIRST_NAMES_M)} {random.choice(LAST)}",
            "birth_year": random.randint(1950, 2016),
            "status": "suspended" if random.random() < 0.04 else "active",
            "fines_eur": random.choice([0, 0, 0, 0, 0, 0, 1.5, 2.0, 3.5, 7.0, 12.5]),
        })
    # Fixture members (used by tests/eligibility_cases.json). Born years are relative to REFERENCE_YEAR.
    fx = [
        (9001, "Fixture Adult",       REFERENCE_YEAR - 35, "active",    0.00),
        (9002, "Fixture Child",       REFERENCE_YEAR - 10, "active",    0.00),
        (9003, "Fixture Suspended",   REFERENCE_YEAR - 40, "suspended", 0.00),
        (9004, "Fixture Fined",       REFERENCE_YEAR - 40, "active",    12.50),
        (9005, "Fixture FineLimit",   REFERENCE_YEAR - 40, "active",    5.00),   # boundary: exactly the limit
        (9006, "Fixture MaxLoans",    REFERENCE_YEAR - 40, "active",    0.00),   # 3 active loans
        (9007, "Fixture TwoLoans",    REFERENCE_YEAR - 40, "active",    0.00),   # 2 active loans
        (9008, "Fixture HasBook",     REFERENCE_YEAR - 40, "active",    0.00),   # already holds B0005
        (9009, "Fixture Age18",       REFERENCE_YEAR - 18, "active",    0.00),   # boundary: exactly 18
        (9010, "Fixture Age17",       REFERENCE_YEAR - 17, "active",    0.00),
        (9011, "Fixture SuspFined",   REFERENCE_YEAR - 40, "suspended", 9.00),
        (9012, "Fixture Racer",       REFERENCE_YEAR - 30, "active",    0.00),   # second user for the last-copy race
    ]
    for mid, name, by, st, fine in fx:
        members.append({"member_id": mid, "name": name, "birth_year": by, "status": st, "fines_eur": fine})
    return members


def make_loans(books, members, copies_total):
    """~800 historical (returned) loans + active loans; keeps copies_available consistent."""
    loans, active_per_book, active_per_member = [], {}, {}
    ids = [b["_id"] for b in books]
    regular = [m["member_id"] for m in members if m["member_id"] < 9000]
    today = date(REFERENCE_YEAR, 6, 1)

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
    # "B0002" has 1 copy and must be fully lent out -> someone (a regular member) holds it
    add(1, "B0002", today - timedelta(days=6), None)

    # Historical returned loans (members tend to prefer a topic -> gives the graph something to find)
    for _ in range(800):
        mid = random.choice(regular)
        bid = random.choice(ids)
        start = today - timedelta(days=random.randint(30, 700))
        add(mid, bid, start, start + timedelta(days=random.randint(5, 30)))

    # Some more active loans by regular members (never exceeding copies or 2 per member)
    tries = 0
    while sum(1 for l in loans if not l["returned_at"]) < 120 and tries < 5000:
        tries += 1
        mid, bid = random.choice(regular), random.choice(ids[10:])      # keep fixture books untouched
        if bid in ("B0001", "B0002", "B0003", "B0004", "B0005"):
            continue
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

    (DATA_DIR / "books.json").write_text(json.dumps(books, indent=1), encoding="utf-8")
    (DATA_DIR / "members.json").write_text(json.dumps(members, indent=1), encoding="utf-8")
    (DATA_DIR / "loans.json").write_text(json.dumps(loans, indent=1), encoding="utf-8")
    print(f"books={len(books)} members={len(members)} loans={len(loans)} "
          f"active_loans={sum(1 for l in loans if not l['returned_at'])}")


if __name__ == "__main__":
    main()
