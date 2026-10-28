from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def embed_documents(texts: Sequence[str]) -> np.ndarray:
    return _get_model().encode_document(list(texts), normalize_embeddings=True)


def embed_query(query: str) -> np.ndarray:
    return _get_model().encode_query(query, normalize_embeddings=True)
