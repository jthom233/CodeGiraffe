"""Multi-agent coordination for concurrent AI-assisted development."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


COORDINATION_DIR = ".codegiraffe"
COORDINATION_FILE = "agents.json"
# Claims expire after this many seconds (default 30 minutes)
DEFAULT_TTL = 1800


@dataclass
class AgentClaim:
    """A claim by an agent on a node or region of the graph."""
    agent_id: str
    node_ids: list[str]
    task: str
    status: str  # "active", "done", "blocked"
    claimed_at: float = field(default_factory=time.time)
    ttl: int = DEFAULT_TTL
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.claimed_at > self.ttl

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentClaim:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CoordinationStore:
    """File-based coordination store for multi-agent status tracking."""

    def _store_path(self, project_path: str) -> Path:
        return Path(project_path).resolve() / COORDINATION_DIR / COORDINATION_FILE

    def _load_claims(self, project_path: str) -> list[AgentClaim]:
        """Load all claims, filtering out expired ones."""
        path = self._store_path(project_path)
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            claims = [AgentClaim.from_dict(c) for c in raw]
            # Filter expired claims
            return [c for c in claims if not c.is_expired]
        except (json.JSONDecodeError, TypeError, KeyError):
            return []

    def _save_claims(self, project_path: str, claims: list[AgentClaim]) -> None:
        """Save claims to disk."""
        path = self._store_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        active = [c for c in claims if not c.is_expired]
        path.write_text(
            json.dumps([c.to_dict() for c in active], indent=2) + "\n",
            encoding="utf-8",
        )

    def claim(
        self,
        project_path: str,
        agent_id: str,
        node_ids: list[str],
        task: str,
        ttl: int = DEFAULT_TTL,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Claim nodes for an agent. Returns claim info or conflict details."""
        claims = self._load_claims(project_path)

        # Check for conflicts (another active agent claiming the same nodes)
        conflicts = []
        for existing in claims:
            if existing.agent_id == agent_id:
                continue
            if existing.status == "done":
                continue
            overlap = set(existing.node_ids) & set(node_ids)
            if overlap:
                conflicts.append({
                    "agent_id": existing.agent_id,
                    "overlapping_nodes": sorted(overlap),
                    "task": existing.task,
                    "status": existing.status,
                })

        if conflicts:
            return {
                "success": False,
                "reason": "conflict",
                "conflicts": conflicts,
            }

        # Remove previous claims by this agent
        claims = [c for c in claims if c.agent_id != agent_id]

        # Add new claim
        new_claim = AgentClaim(
            agent_id=agent_id,
            node_ids=node_ids,
            task=task,
            status="active",
            ttl=ttl,
            metadata=metadata or {},
        )
        claims.append(new_claim)
        self._save_claims(project_path, claims)

        return {
            "success": True,
            "claim": new_claim.to_dict(),
        }

    def update_status(
        self,
        project_path: str,
        agent_id: str,
        status: str,
        task: str | None = None,
    ) -> dict[str, Any]:
        """Update an agent's status."""
        claims = self._load_claims(project_path)

        for claim in claims:
            if claim.agent_id == agent_id:
                claim.status = status
                if task is not None:
                    claim.task = task
                # Refresh the TTL on update
                claim.claimed_at = time.time()
                self._save_claims(project_path, claims)
                return {"success": True, "claim": claim.to_dict()}

        return {"success": False, "reason": f"No active claim found for agent '{agent_id}'."}

    def release(self, project_path: str, agent_id: str) -> dict[str, Any]:
        """Release an agent's claim."""
        claims = self._load_claims(project_path)
        before = len(claims)
        claims = [c for c in claims if c.agent_id != agent_id]
        self._save_claims(project_path, claims)

        removed = before - len(claims)
        return {"success": True, "released": removed}

    def list_agents(self, project_path: str) -> list[dict[str, Any]]:
        """List all active agents and their claims."""
        claims = self._load_claims(project_path)
        return [c.to_dict() for c in claims]
