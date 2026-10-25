"""Turns text into normalised 384-d vectors with all-MiniLM-L6-v2 (via fastembed/ONNX).
The SAME function is used for pgvector and Qdrant, so both hold identical vectors."""
import numpy as np
from fastembed import TextEmbedding

from .config import EMBED_MODEL

_model = None


def embed(texts):
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBED_MODEL)
    v = np.array(list(_model.embed(list(texts))), dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)      # unit length -> cosine == dot product
