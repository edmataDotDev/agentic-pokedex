import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from pokedex.config import get_settings
from pokedex.rag.embedder import MODEL_NAME, embed_query
from pokedex.rag.exceptions import InvalidIndexError
from pokedex.rag.indexer import CHUNKS_FILE, EMBEDDINGS_FILE

TOP_K = 5


@dataclass(frozen=True)
class _Index:
    embeddings: np.ndarray
    chunks: list[dict]


_executor = ThreadPoolExecutor(max_workers=1)
_preload_lock = threading.Lock()
_query_lock = threading.Lock()
_index_future: Future[_Index | None] | None = None


def _load_index() -> _Index | None:
    index_location = get_settings().index_location
    embeddings_path = index_location / EMBEDDINGS_FILE
    chunks_path = index_location / CHUNKS_FILE
    if not embeddings_path.exists() or not chunks_path.exists():
        return None

    try:
        embeddings = np.load(embeddings_path)
        payload = json.loads(chunks_path.read_text(encoding="utf-8"))
        chunks = payload["chunks"]
        index_model = payload["model"]
        dimension = payload["dimension"]
    except (OSError, ValueError, KeyError) as exc:
        raise InvalidIndexError(
            f"The lore index is unreadable ({exc}). Rebuild it with `pokedex-index`."
        ) from exc

    if index_model != MODEL_NAME:
        raise InvalidIndexError(
            f"The lore index was built with {index_model}, but the current model is "
            f"{MODEL_NAME}. Rebuild it with `pokedex-index`."
        )
    if embeddings.shape != (len(chunks), dimension):
        raise InvalidIndexError(
            f"The lore index is inconsistent: the vector matrix has shape {embeddings.shape}, "
            f"but the metadata declares {len(chunks)} chunks of dimension {dimension}. "
            f"Rebuild it with `pokedex-index`."
        )

    # Loads the embedding model now so the first real search doesn't pay for it.
    embed_query("warm up")
    return _Index(embeddings, chunks)


def preload_index() -> Future[_Index | None]:
    global _index_future
    with _preload_lock:
        if _index_future is None:
            _index_future = _executor.submit(_load_index)
        return _index_future


def _to_result(chunk: dict, score: float) -> dict:
    return {
        "pokemon": chunk["pokemon"],
        "generation": chunk["generation"],
        "section": chunk["section"],
        "source": chunk["source"],
        "score": round(score, 3),
        "text": chunk["text"].partition("\n\n")[2],
    }


def search_lore(query: str) -> dict:
    index = preload_index().result()
    if index is None or not isinstance(query, str) or not query.strip():
        return {"results": []}

    with _query_lock:
        query_vector = embed_query(query)
    scores = index.embeddings @ query_vector
    best = np.argsort(scores)[::-1][:TOP_K]
    return {"results": [_to_result(index.chunks[i], float(scores[i])) for i in best]}
