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


def truncated_indices(texts: Sequence[str]) -> list[int]:
    model = _get_model()
    limit = model.max_seq_length
    if limit is None:
        return []
    token_ids = model.tokenizer(list(texts))["input_ids"]
    return [i for i, ids in enumerate(token_ids) if len(ids) > limit]
