"""Connection settings and shared constants. Everything else imports from here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

# --- connections (match docker-compose.yml) ---
PG_DSN = "postgresql://library:library@localhost:5433/library"
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "library"
REDIS_URL = "redis://localhost:6379/0"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "librarypass")
QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "books"

# --- business constants (the loan rules) ---
REFERENCE_YEAR = 2026        # fixed "today" so ages (and test results) never change over time
MAX_ACTIVE_LOANS = 3         # a member may hold at most 3 books at once
FINE_LIMIT_EUR = 5.00        # fines ABOVE this block new loans (exactly 5.00 is still fine)
DECISION_TTL_SECONDS = 300   # how long a cached decision lives in Redis

# --- vectors ---
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
