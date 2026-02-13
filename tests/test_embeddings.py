"""Tests for embedding-based context scoring (codegiraffe.embeddings)."""

import json

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from codegiraffe.embeddings import (
    cosine_similarity,
    EmbeddingCache,
    node_to_text,
    is_available,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 1.0]
        assert cosine_similarity(a, b) == 0.0

    def test_similar_vectors(self):
        a = [1.0, 1.0, 0.0]
        b = [1.0, 0.9, 0.1]
        score = cosine_similarity(a, b)
        assert 0.9 < score < 1.0


class TestEmbeddingCache:
    def test_set_and_get(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path))
        cache.set("key1", [1.0, 2.0, 3.0])
        assert cache.get("key1") == [1.0, 2.0, 3.0]

    def test_get_missing(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path))
        assert cache.get("nonexistent") is None

    def test_save_and_reload(self, tmp_path):
        cache1 = EmbeddingCache(str(tmp_path))
        cache1.set("key1", [1.0, 2.0])
        cache1.save()

        cache2 = EmbeddingCache(str(tmp_path))
        assert cache2.get("key1") == [1.0, 2.0]

    def test_cache_key_deterministic(self):
        key1 = EmbeddingCache.cache_key("hello world")
        key2 = EmbeddingCache.cache_key("hello world")
        assert key1 == key2

    def test_cache_key_different_inputs(self):
        key1 = EmbeddingCache.cache_key("hello")
        key2 = EmbeddingCache.cache_key("world")
        assert key1 != key2

    def test_corrupted_cache_file(self, tmp_path):
        cache_path = tmp_path / ".codegiraffe" / "embeddings.json"
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("not json!!!")

        cache = EmbeddingCache(str(tmp_path))
        assert cache.get("anything") is None  # Should not crash


class TestNodeToText:
    def test_basic(self):
        text = node_to_text("endpoint:/api/users", "endpoint", "GET /api/users", "api/routes.py", {})
        assert "endpoint" in text
        assert "GET /api/users" in text
        assert "api/routes.py" in text

    def test_with_metadata(self):
        text = node_to_text("table:users", "database_table", "users", None, {"class_name": "User"})
        assert "database table" in text  # _ replaced with space
        assert "User" in text

    def test_internal_metadata_excluded(self):
        text = node_to_text("x", "service", "x", None, {"_relevance_score": 5, "name": "test"})
        assert "_relevance_score" not in text
        assert "test" in text

    def test_empty_label_uses_id(self):
        text = node_to_text("env:PORT", "env_var", "", None, {})
        assert "env:PORT" in text


class TestIsAvailable:
    def test_returns_bool(self):
        result = is_available()
        assert isinstance(result, bool)


class TestContextForTaskFallback:
    """Test that context_for_task falls back to keywords when embeddings unavailable."""

    def test_keyword_fallback(self, sample_graph):
        from codegiraffe.query import context_for_task

        # Force keyword mode
        result = context_for_task(sample_graph, "user endpoint", use_embeddings=False)
        assert len(result.nodes) > 0

    def test_keyword_fallback_when_unavailable(self, sample_graph):
        from codegiraffe.query import context_for_task

        with patch("codegiraffe.embeddings.is_available", return_value=False):
            result = context_for_task(sample_graph, "user endpoint", use_embeddings=True)
            assert len(result.nodes) > 0  # Should still work via keyword fallback
