import logging
import os
from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _get_model() -> "SentenceTransformer":
    # Imported here, not at module level: importing torch takes seconds and would block
    # CLI startup. The env vars must be set before that import for the libraries to see them.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)

    from sentence_transformers import SentenceTransformer
    from transformers.utils import logging as transformers_logging

    transformers_logging.disable_progress_bar()
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
