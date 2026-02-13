"""Embedding-based context scoring for semantic task matching.

Uses sentence-transformers for embedding generation when available.
Falls back gracefully to keyword scoring when the library is not installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache directory for pre-computed embeddings
_CACHE_DIR = ".codegiraffe"
_EMBEDDING_CACHE_FILE = "embeddings.json"

# Lazy-loaded model
_model: Any = None
_model_name: str = "all-MiniLM-L6-v2"
_available: bool | None = None  # None = not checked yet


def is_available() -> bool:
    """Check if sentence-transformers is installed."""
    global _available
    if _available is None:
        try:
            import sentence_transformers  # noqa: F401

            _available = True
        except ImportError:
            _available = False
    return _available


def _get_model():
    """Lazy-load the sentence-transformers model."""
    global _model
    if _model is None:
        if not is_available():
            raise RuntimeError("sentence-transformers is not installed")
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_model_name)
    return _model


def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text."""
    model = _get_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in a single batch."""
    model = _get_model()
    embeddings = model.encode(texts, convert_to_numpy=True, batch_size=32)
    return embeddings.tolist()


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors using only stdlib."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingCache:
    """File-based cache for node embeddings to avoid recomputing."""

    def __init__(self, project_path: str):
        self._path = Path(project_path).resolve() / _CACHE_DIR / _EMBEDDING_CACHE_FILE
        self._data: dict[str, list[float]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path.is_file():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._data = raw
            except (json.JSONDecodeError, TypeError):
                self._data = {}

    def get(self, key: str) -> list[float] | None:
        self._load()
        return self._data.get(key)

    def set(self, key: str, embedding: list[float]) -> None:
        self._load()
        self._data[key] = embedding

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def cache_key(text: str) -> str:
        """Generate a stable cache key for a piece of text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def node_to_text(
    node_id: str,
    node_type: str,
    label: str,
    file_path: str | None,
    metadata: dict,
) -> str:
    """Convert a node to a text representation suitable for embedding."""
    parts = [node_type.replace("_", " "), label or node_id]
    if file_path:
        parts.append(f"in {file_path}")
    # Add relevant metadata
    for key, value in metadata.items():
        if not key.startswith("_") and isinstance(value, str):
            parts.append(f"{key}: {value}")
    return " ".join(parts)


def score_nodes_by_embedding(
    task: str,
    nodes: list[tuple[str, str]],  # list of (node_id, node_text_representation)
    project_path: str | None = None,
) -> list[tuple[str, float]]:
    """Score nodes by semantic similarity to the task description.

    Parameters
    ----------
    task : str
        The natural language task description.
    nodes : list of (node_id, text)
        Each node's ID and a text representation for embedding.
    project_path : str, optional
        If provided, use file-based caching for node embeddings.

    Returns
    -------
    list of (node_id, score)
        Nodes scored by cosine similarity to the task, descending.
    """
    if not is_available():
        raise RuntimeError("sentence-transformers is not installed")

    cache = EmbeddingCache(project_path) if project_path else None

    # Embed the task
    task_embedding = embed_text(task)

    # Embed nodes (with caching)
    node_embeddings: list[tuple[str, list[float]]] = []
    texts_to_embed: list[tuple[int, str, str]] = []  # (index, node_id, text)

    for i, (node_id, text) in enumerate(nodes):
        if cache:
            key = EmbeddingCache.cache_key(text)
            cached = cache.get(key)
            if cached is not None:
                node_embeddings.append((node_id, cached))
                continue
        texts_to_embed.append((i, node_id, text))

    # Batch embed uncached nodes
    if texts_to_embed:
        batch_texts = [t[2] for t in texts_to_embed]
        batch_embeddings = embed_texts(batch_texts)
        for (_, node_id, text), emb in zip(texts_to_embed, batch_embeddings):
            node_embeddings.append((node_id, emb))
            if cache:
                cache.set(EmbeddingCache.cache_key(text), emb)

    # Save cache
    if cache:
        cache.save()

    # Score by cosine similarity
    scored = [
        (nid, cosine_similarity(task_embedding, emb)) for nid, emb in node_embeddings
    ]
    scored.sort(key=lambda x: -x[1])
    return scored
