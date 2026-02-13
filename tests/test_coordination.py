"""Tests for multi-agent coordination (codegiraffe.coordination)."""
import json
import time
import pytest
from pathlib import Path
from codegiraffe.coordination import AgentClaim, CoordinationStore, DEFAULT_TTL


@pytest.fixture
def store():
    return CoordinationStore()


class TestAgentClaim:
    def test_create_claim(self):
        claim = AgentClaim(
            agent_id="agent-1",
            node_ids=["endpoint:/api/users"],
            task="Refactoring user endpoint",
            status="active",
        )
        assert claim.agent_id == "agent-1"
        assert not claim.is_expired

    def test_expired_claim(self):
        claim = AgentClaim(
            agent_id="agent-1",
            node_ids=["endpoint:/api/users"],
            task="Old task",
            status="active",
            claimed_at=time.time() - DEFAULT_TTL - 1,
        )
        assert claim.is_expired

    def test_round_trip(self):
        claim = AgentClaim(
            agent_id="agent-1",
            node_ids=["a", "b"],
            task="test",
            status="active",
            metadata={"key": "value"},
        )
        d = claim.to_dict()
        restored = AgentClaim.from_dict(d)
        assert restored.agent_id == claim.agent_id
        assert restored.node_ids == claim.node_ids
        assert restored.metadata == claim.metadata


class TestCoordinationStore:
    def test_claim_success(self, store, tmp_path):
        result = store.claim(str(tmp_path), "agent-1", ["node:a"], "Working on A")
        assert result["success"] is True

    def test_claim_conflict(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working on A")
        result = store.claim(str(tmp_path), "agent-2", ["node:a"], "Also working on A")
        assert result["success"] is False
        assert result["reason"] == "conflict"
        assert len(result["conflicts"]) == 1

    def test_claim_no_conflict_different_nodes(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working on A")
        result = store.claim(str(tmp_path), "agent-2", ["node:b"], "Working on B")
        assert result["success"] is True

    def test_claim_replaces_previous(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "First task")
        store.claim(str(tmp_path), "agent-1", ["node:b"], "Second task")
        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 1
        assert agents[0]["node_ids"] == ["node:b"]

    def test_update_status(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working")
        result = store.update_status(str(tmp_path), "agent-1", "done")
        assert result["success"] is True
        assert result["claim"]["status"] == "done"

    def test_update_nonexistent_agent(self, store, tmp_path):
        result = store.update_status(str(tmp_path), "ghost", "active")
        assert result["success"] is False

    def test_release(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Working")
        result = store.release(str(tmp_path), "agent-1")
        assert result["success"] is True
        assert result["released"] == 1
        assert store.list_agents(str(tmp_path)) == []

    def test_list_agents(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Task 1")
        store.claim(str(tmp_path), "agent-2", ["node:b"], "Task 2")
        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 2

    def test_expired_claims_filtered(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Old task", ttl=0)
        # Force expiration
        time.sleep(0.1)
        agents = store.list_agents(str(tmp_path))
        assert len(agents) == 0

    def test_done_agent_no_conflict(self, store, tmp_path):
        store.claim(str(tmp_path), "agent-1", ["node:a"], "Done task")
        store.update_status(str(tmp_path), "agent-1", "done")
        result = store.claim(str(tmp_path), "agent-2", ["node:a"], "New task")
        assert result["success"] is True

    def test_empty_store(self, store, tmp_path):
        agents = store.list_agents(str(tmp_path))
        assert agents == []
