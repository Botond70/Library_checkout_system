"""MongoDB collection with a $jsonSchema validator.

One collection, two kinds of book: every book needs the common fields; then a FICTION book must also
list the people (characters) it is about, and a NONFICTION book the places it is about. These are the
real Open Library fields `subject_people` / `subject_places`. validationAction "error" means an
invalid insert is REJECTED, not just logged.
"""

COMMON = ["_id", "ol_key", "title", "author", "genre", "kind", "min_age", "description", "updated_at"]


def _variant(kind, extra_required, extra_props):
    return {
        "bsonType": "object",
        "required": extra_required,
        "properties": {"kind": {"enum": [kind]}, **extra_props},
    }


VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": COMMON,
    "properties": {
        "_id": {"bsonType": "string"},
        "ol_key": {"bsonType": "string"},
        "title": {"bsonType": "string", "minLength": 1},
        "min_age": {"bsonType": "int", "minimum": 0, "maximum": 18},
        "kind": {"enum": ["fiction", "nonfiction"]},
        "description": {"bsonType": "string", "minLength": 10},
        "pages": {"bsonType": ["int", "double"], "minimum": 1},
    },
    "oneOf": [
        _variant("fiction", ["subject_people"], {"subject_people": {"bsonType": "array"}}),
        _variant("nonfiction", ["subject_places"], {"subject_places": {"bsonType": "array"}}),
    ],
}}


def create_books_collection(db):
    db.drop_collection("books")
    db.create_collection("books", validator=VALIDATOR, validationAction="error", validationLevel="strict")
    db.books.create_index([("genre", 1)])
