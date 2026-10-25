"""MongoDB collection with a $jsonSchema validator.

One collection, three formats: every book needs the common fields, and then the fields of its
own format (novel -> pages + isbn, audiobook -> duration + narrator, graphic_novel -> artist +
issue number). validationAction "error" means an invalid insert is REJECTED, not just logged.
"""

COMMON = ["_id", "title", "author", "genre", "format", "min_age", "description", "updated_at"]


def _variant(fmt, extra_required, extra_props):
    return {
        "bsonType": "object",
        "required": extra_required,
        "properties": {"format": {"enum": [fmt]}, **extra_props},
    }


VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": COMMON,
    "properties": {
        "_id": {"bsonType": "string"},
        "title": {"bsonType": "string", "minLength": 1},
        "min_age": {"bsonType": "int", "minimum": 0, "maximum": 18},
        "format": {"enum": ["novel", "audiobook", "graphic_novel"]},
        "description": {"bsonType": "string", "minLength": 10},
    },
    "oneOf": [
        _variant("novel", ["pages", "isbn"],
                 {"pages": {"bsonType": "int", "minimum": 1}, "isbn": {"bsonType": "string"}}),
        _variant("audiobook", ["duration_minutes", "narrator"],
                 {"duration_minutes": {"bsonType": "int", "minimum": 1}, "narrator": {"bsonType": "string"}}),
        _variant("graphic_novel", ["artist", "issue_number"],
                 {"artist": {"bsonType": "string"}, "issue_number": {"bsonType": "int"}}),
    ],
}}


def create_books_collection(db):
    db.drop_collection("books")
    db.create_collection("books", validator=VALIDATOR, validationAction="error", validationLevel="strict")
    db.books.create_index([("genre", 1)])
