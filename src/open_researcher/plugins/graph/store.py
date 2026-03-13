"""CRUD operations for hypotheses and evidence in the state database."""
from __future__ import annotations

import time
from typing import Any

from open_researcher.plugins.storage.db import Database


class GraphStore:
    """SQLite-backed store for the hypothesis/evidence graph."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Hypotheses
    # ------------------------------------------------------------------

    async def add_hypothesis(
        self,
        *,
        id: str,
        claim: str,
        status: str = "proposed",
        parent_id: str | None = None,
        metadata: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new hypothesis and return it as a dict."""
        now = time.time()
        self._db.conn.execute(
            "INSERT INTO hypotheses (id, claim, status, parent_id, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, claim, status, parent_id, now, metadata),
        )
        self._db.conn.commit()
        return {
            "id": id,
            "claim": claim,
            "status": status,
            "parent_id": parent_id,
            "created_at": now,
            "metadata": metadata,
        }

    async def get_hypothesis(self, hypothesis_id: str) -> dict[str, Any] | None:
        """Return a single hypothesis by id, or ``None`` if not found."""
        row = self._db.conn.execute(
            "SELECT id, claim, status, parent_id, created_at, metadata "
            "FROM hypotheses WHERE id = ?",
            (hypothesis_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(
            zip(
                ("id", "claim", "status", "parent_id", "created_at", "metadata"),
                row,
            )
        )

    async def update_hypothesis(
        self,
        hypothesis_id: str,
        *,
        status: str | None = None,
        claim: str | None = None,
        metadata: str | None = None,
    ) -> None:
        """Update mutable fields of an existing hypothesis."""
        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if claim is not None:
            updates.append("claim = ?")
            params.append(claim)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(metadata)
        if not updates:
            return
        params.append(hypothesis_id)
        self._db.conn.execute(
            f"UPDATE hypotheses SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self._db.conn.commit()

    async def list_hypotheses(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all hypotheses, optionally filtered by *status*."""
        if status is not None:
            rows = self._db.conn.execute(
                "SELECT id, claim, status, parent_id, created_at, metadata "
                "FROM hypotheses WHERE status = ?",
                (status,),
            ).fetchall()
        else:
            rows = self._db.conn.execute(
                "SELECT id, claim, status, parent_id, created_at, metadata "
                "FROM hypotheses",
            ).fetchall()
        cols = ("id", "claim", "status", "parent_id", "created_at", "metadata")
        return [dict(zip(cols, r)) for r in rows]

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    async def add_evidence(
        self,
        *,
        id: str,
        hypothesis_id: str,
        experiment_id: int | None = None,
        direction: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new piece of evidence linked to a hypothesis."""
        now = time.time()
        self._db.conn.execute(
            "INSERT INTO evidence (id, hypothesis_id, experiment_id, direction, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, hypothesis_id, experiment_id, direction, summary, now),
        )
        self._db.conn.commit()
        return {
            "id": id,
            "hypothesis_id": hypothesis_id,
            "experiment_id": experiment_id,
            "direction": direction,
            "summary": summary,
            "created_at": now,
        }

    async def list_evidence(
        self,
        *,
        hypothesis_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return evidence rows, optionally filtered by *hypothesis_id*."""
        cols = ("id", "hypothesis_id", "experiment_id", "direction", "summary", "created_at")
        if hypothesis_id is not None:
            rows = self._db.conn.execute(
                "SELECT id, hypothesis_id, experiment_id, direction, summary, created_at "
                "FROM evidence WHERE hypothesis_id = ?",
                (hypothesis_id,),
            ).fetchall()
        else:
            rows = self._db.conn.execute(
                "SELECT id, hypothesis_id, experiment_id, direction, summary, created_at "
                "FROM evidence",
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]
