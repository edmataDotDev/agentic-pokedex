import json
import os
from dataclasses import asdict
from pathlib import Path

import numpy as np

from pokedex.config import get_settings
from pokedex.rag.chunking import Chunk, chunk_markdown
from pokedex.rag.embedder import MODEL_NAME, embed_documents, truncated_indices

EMBEDDINGS_FILE = "embeddings.npy"
CHUNKS_FILE = "chunks.json"


def _collect_chunks(documents_location: Path) -> list[Chunk]:
    return [
        chunk
        for path in sorted(documents_location.glob("gen-*/*.md"))
        for chunk in chunk_markdown(path)
    ]


def _write_index(index_location: Path, embeddings: np.ndarray, chunks: list[Chunk]) -> None:
    index_location.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": MODEL_NAME,
        "dimension": embeddings.shape[1],
        "chunks": [asdict(chunk) for chunk in chunks],
    }

    embeddings_tmp = index_location / f"{EMBEDDINGS_FILE}.tmp"
    chunks_tmp = index_location / f"{CHUNKS_FILE}.tmp"
    with embeddings_tmp.open("wb") as file:
        np.save(file, embeddings)
    chunks_tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    os.replace(embeddings_tmp, index_location / EMBEDDINGS_FILE)
    os.replace(chunks_tmp, index_location / CHUNKS_FILE)


def main() -> None:
    settings = get_settings()
    chunks = _collect_chunks(settings.documents_location)
    if not chunks:
        raise SystemExit(
            f"No chunks found: expected gen-<N>/<Pokemon>.md files under {settings.documents_location}"
        )

    texts = [chunk.text for chunk in chunks]
    embeddings = embed_documents(texts)
    truncated = truncated_indices(texts)
    _write_index(settings.index_location, embeddings, chunks)

    print(f"Indexed {len(chunks)} chunks with {MODEL_NAME} -> {settings.index_location}")
    if truncated:
        print(f"WARNING: {len(truncated)} chunks exceed the model's token window and were truncated:")
        for i in truncated:
            print(f"  {chunks[i].pokemon} | {chunks[i].section}")
