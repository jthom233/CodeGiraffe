"""Tests for the compute_layout() function in codegiraffe.layout.

These are TDD RED-phase tests written before the implementation exists.
All tests are expected to fail with ImportError until layout.py is implemented.
"""

from __future__ import annotations

import builtins
from typing import Any
from unittest.mock import patch

import pytest

from codegiraffe.layout import compute_layout
from codegiraffe.graph import GraphData, Node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph(*node_ids: str) -> GraphData:
    """Build a minimal GraphData with the given node IDs (all type='service')."""
    nodes = {
        nid: Node(id=nid, type="service", label=nid.capitalize())
        for nid in node_ids
    }
    return GraphData(nodes=nodes)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestComputeLayout:
    """Unit tests for compute_layout(graph_data) -> dict[str, list[float]]."""

    # ------------------------------------------------------------------
    # a) Returns correct type
    # ------------------------------------------------------------------

    def test_returns_dict(self) -> None:
        """compute_layout() must return a dict."""
        graph = _make_graph("n1", "n2", "n3")
        result = compute_layout(graph)
        assert isinstance(result, dict), (
            f"Expected dict, got {type(result).__name__}"
        )

    def test_keys_are_strings(self) -> None:
        """Every key in the returned dict must be a string (node ID)."""
        graph = _make_graph("svc:auth", "ep:login", "db:users")
        result = compute_layout(graph)
        for key in result:
            assert isinstance(key, str), (
                f"Key {key!r} is not a string"
            )

    def test_values_are_lists(self) -> None:
        """Every value in the returned dict must be a list."""
        graph = _make_graph("n1", "n2", "n3")
        result = compute_layout(graph)
        for node_id, coords in result.items():
            assert isinstance(coords, list), (
                f"Value for {node_id!r} is {type(coords).__name__}, expected list"
            )

    # ------------------------------------------------------------------
    # b) One entry per node
    # ------------------------------------------------------------------

    def test_one_entry_per_node(self) -> None:
        """The returned dict must have exactly one entry per node in the graph."""
        graph = _make_graph("a", "b", "c")
        result = compute_layout(graph)
        assert len(result) == 3, (
            f"Expected 3 entries (one per node), got {len(result)}"
        )

    def test_entry_keys_match_node_ids(self) -> None:
        """The keys of the returned dict must exactly match the node IDs."""
        node_ids = {"svc:auth", "ep:login", "db:users"}
        graph = _make_graph(*node_ids)
        result = compute_layout(graph)
        assert set(result.keys()) == node_ids, (
            f"Key mismatch: expected {node_ids}, got {set(result.keys())}"
        )

    # ------------------------------------------------------------------
    # c) All values are 2-element float lists
    # ------------------------------------------------------------------

    def test_each_value_has_exactly_two_elements(self) -> None:
        """Every value in the returned dict must be a list of exactly 2 elements."""
        graph = _make_graph("x", "y", "z")
        result = compute_layout(graph)
        for node_id, coords in result.items():
            assert len(coords) == 2, (
                f"Coords for {node_id!r} has {len(coords)} elements, expected 2"
            )

    def test_each_coordinate_is_numeric(self) -> None:
        """Both coordinates for every node must be int or float (numeric)."""
        graph = _make_graph("n1", "n2", "n3")
        result = compute_layout(graph)
        for node_id, coords in result.items():
            for i, val in enumerate(coords):
                assert isinstance(val, (int, float)), (
                    f"Coord[{i}] for {node_id!r} is {type(val).__name__}, "
                    "expected int or float"
                )

    # ------------------------------------------------------------------
    # d) Works when fa2 is unavailable (grid fallback)
    # ------------------------------------------------------------------

    def test_grid_fallback_when_fa2_unavailable(self) -> None:
        """When fa2 cannot be imported, compute_layout() must still return a
        valid dict (one entry per node, each a 2-element numeric list)."""
        original_import = builtins.__import__

        def _block_fa2(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "fa2" or name.startswith("fa2."):
                raise ImportError(f"Mocked: {name} is not available")
            return original_import(name, *args, **kwargs)

        graph = _make_graph("a", "b", "c")

        with patch("builtins.__import__", side_effect=_block_fa2):
            result = compute_layout(graph)

        assert isinstance(result, dict), "Fallback must return a dict"
        assert len(result) == 3, (
            f"Fallback must return one entry per node, got {len(result)}"
        )
        for node_id, coords in result.items():
            assert isinstance(coords, list) and len(coords) == 2, (
                f"Fallback coords for {node_id!r} must be a 2-element list"
            )
            for val in coords:
                assert isinstance(val, (int, float)), (
                    f"Fallback coord for {node_id!r} must be numeric, got "
                    f"{type(val).__name__}"
                )

    # ------------------------------------------------------------------
    # e) Empty graph returns empty dict
    # ------------------------------------------------------------------

    def test_empty_graph_returns_empty_dict(self) -> None:
        """compute_layout() on an empty GraphData must return {}."""
        graph = GraphData()  # no nodes
        result = compute_layout(graph)
        assert result == {}, (
            f"Expected empty dict for empty graph, got {result!r}"
        )

    def test_empty_graph_result_is_dict_type(self) -> None:
        """Even for an empty graph the return type must be dict, not None."""
        graph = GraphData()
        result = compute_layout(graph)
        assert isinstance(result, dict), (
            f"Expected dict for empty graph, got {type(result).__name__}"
        )

    # ------------------------------------------------------------------
    # f) Single-node graph returns one entry
    # ------------------------------------------------------------------

    def test_single_node_graph_returns_one_entry(self) -> None:
        """compute_layout() on a single-node graph must return exactly one entry."""
        graph = _make_graph("solo")
        result = compute_layout(graph)
        assert len(result) == 1, (
            f"Expected 1 entry for single-node graph, got {len(result)}"
        )

    def test_single_node_key_matches_node_id(self) -> None:
        """The single entry's key must be the node's ID."""
        graph = _make_graph("solo")
        result = compute_layout(graph)
        assert "solo" in result, (
            f"Expected key 'solo' in result, got keys: {list(result.keys())}"
        )

    def test_single_node_value_is_two_element_numeric_list(self) -> None:
        """The single entry's value must be a 2-element list of numerics."""
        graph = _make_graph("solo")
        result = compute_layout(graph)
        coords = result.get("solo")
        assert isinstance(coords, list), (
            f"Expected list for 'solo', got {type(coords).__name__}"
        )
        assert len(coords) == 2, (
            f"Expected 2 coordinates for 'solo', got {len(coords)}"
        )
        for i, val in enumerate(coords):
            assert isinstance(val, (int, float)), (
                f"Coord[{i}] for 'solo' must be numeric, got "
                f"{type(val).__name__}"
            )
