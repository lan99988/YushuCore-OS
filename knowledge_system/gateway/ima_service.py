"""IMA-backed, permission-filtered knowledge gateway.

The offline cache is a per-agent, per-query projection of already authorized
summaries. It is deliberately not a local knowledge repository.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from integrations.base import AdapterError
from integrations.ima import PulledItem
from knowledge_system.gateway.models import AgentPolicy, ContextResponse, GatewayNode, QueryResponse
from knowledge_system.gateway.permissions import check_read_permission
from knowledge_system.gateway.service import PermissionDenied


class KnowledgeUnavailable(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


class ImaKnowledgeGateway:
    def __init__(
        self,
        *,
        cache_path: str | Path,
        adapter: Any | None,
        sources: Mapping[str, Mapping[str, str]],
        policies: Mapping[str, AgentPolicy],
        agent_credentials: Mapping[str, str],
    ) -> None:
        if set(policies) != set(agent_credentials):
            raise ValueError("every agent policy must have a credential")
        self.adapter = adapter
        self.sources = dict(sources)
        self.policies = dict(policies)
        self._credential_hashes = {
            agent: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for agent, value in agent_credentials.items()
        }
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS authorized_summary_cache (
                agent_id TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                cached_at TEXT NOT NULL,
                nodes_json TEXT NOT NULL,
                PRIMARY KEY (agent_id, query_hash)
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.cache_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _policy(self, agent_id: str, credential: str) -> AgentPolicy:
        expected = self._credential_hashes.get(agent_id)
        actual = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        if not credential or expected is None or not hmac.compare_digest(expected, actual):
            raise PermissionDenied("agent_credential_invalid")
        return self.policies[agent_id]

    def _cache_key(self, query: str) -> str:
        return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()

    def _cached(self, query: str, agent_id: str, policy: AgentPolicy) -> QueryResponse | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT cached_at, nodes_json FROM authorized_summary_cache WHERE agent_id=? AND query_hash=?",
                (agent_id, self._cache_key(query)),
            ).fetchone()
        if row is None:
            return None
        nodes = [GatewayNode(**{**raw, "domain": tuple(raw["domain"])}) for raw in json.loads(row[1])]
        permitted = []
        for node in nodes:
            kb_id = node.metadata.get("knowledge_base_id")
            source = self.sources.get(kb_id)
            if source is None:
                continue
            current = replace(node, domain=(source["domain"],),
                              sensitivity=source.get("sensitivity", "level_0"))
            if check_read_permission(current, agent_id, policy).allowed:
                permitted.append(current)
        if not permitted:
            return None
        return QueryResponse(
            nodes=permitted, permission="approved", denied_count=len(nodes) - len(permitted),
            invalid_count=0, source="ima_cache", stale=True, partial=True, cached_at=row[0],
        )

    def _save(self, query: str, agent_id: str, nodes: list[GatewayNode], cached_at: str) -> None:
        # Never cache an empty or denied result: absence cannot prove completeness offline.
        if not nodes:
            return
        projection = [asdict(node) for node in nodes]
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO authorized_summary_cache VALUES (?, ?, ?, ?)",
                (agent_id, self._cache_key(query), cached_at, json.dumps(projection, ensure_ascii=False)),
            )

    def _map_items(self, kb_id: str, source: Mapping[str, str], items: list[dict],
                   agent_id: str, policy: AgentPolicy) -> tuple[list[GatewayNode], int, int]:
        nodes: list[GatewayNode] = []
        denied = invalid = 0
        for raw in items:
            try:
                item = PulledItem.from_api(raw, knowledge_base_id=kb_id)
                node = GatewayNode(
                    id=f"ima:{kb_id}:{item.media_id}", type="knowledge",
                    title=item.title, domain=(source["domain"],), status="validated",
                    confidence=1.0, sensitivity=source.get("sensitivity", "level_0"),
                    path=f"ima/{kb_id}/{item.media_id}", body=item.introduction,
                    metadata={"agent_access": ["*"], "source": "ima", "media_id": item.media_id,
                              "knowledge_base_id": kb_id},
                )
                if check_read_permission(node, agent_id, policy).allowed:
                    nodes.append(node)
                else:
                    denied += 1
            except (AdapterError, KeyError, TypeError, ValueError):
                invalid += 1
        return nodes, denied, invalid

    @staticmethod
    def _error_code(exc: Exception) -> str:
        message = str(exc).lower()
        return "auth_required" if "401" in message or "unauthorized" in message else "provider_unavailable"

    def query_knowledge(self, query: str, *, agent_id: str, credential: str) -> QueryResponse:
        policy = self._policy(agent_id, credential)
        if not query.strip():
            raise ValueError("query_empty")
        if not self.sources or self.adapter is None:
            cached = self._cached(query, agent_id, policy)
            if cached is not None:
                return cached
            raise KnowledgeUnavailable("not_configured" if not self.sources or self.adapter is None else "offline")

        nodes: list[GatewayNode] = []
        denied = invalid = 0
        partial = False
        try:
            for kb_id, source in self.sources.items():
                cursor = ""
                seen_cursors = {cursor}
                for _ in range(5):
                    response = self.adapter.search_items(kb_id, query.strip(), cursor=cursor) if cursor else self.adapter.search_items(kb_id, query.strip())
                    mapped, rejected, malformed = self._map_items(
                        kb_id, source, response.get("items", []), agent_id, policy)
                    nodes.extend(mapped)
                    denied += rejected
                    invalid += malformed
                    if response.get("is_end", True):
                        break
                    cursor = response.get("next_cursor", "")
                    if not cursor or cursor in seen_cursors:
                        partial = True
                        break
                    seen_cursors.add(cursor)
                else:
                    partial = True
        except Exception as exc:
            cached = self._cached(query, agent_id, policy)
            if cached is not None:
                return cached
            raise KnowledgeUnavailable(self._error_code(exc)) from None

        now = datetime.now(timezone.utc).isoformat()
        self._save(query, agent_id, nodes, now)
        return QueryResponse(nodes=nodes, permission="approved", denied_count=denied,
                             invalid_count=invalid, source="ima", stale=False, partial=partial,
                             cached_at=now)

    def list_knowledge(self, *, agent_id: str, credential: str) -> QueryResponse:
        policy = self._policy(agent_id, credential)
        cache_query = "__ima_list__"
        if not self.sources or self.adapter is None:
            cached = self._cached(cache_query, agent_id, policy)
            if cached is not None:
                return cached
            raise KnowledgeUnavailable("not_configured")
        nodes: list[GatewayNode] = []
        denied = invalid = 0
        partial = False
        try:
            for kb_id, source in self.sources.items():
                cursor = ""
                seen_cursors = {cursor}
                for _ in range(5):
                    response = self.adapter.list_items(kb_id, limit=50, cursor=cursor) if cursor else self.adapter.list_items(kb_id, limit=50)
                    mapped, rejected, malformed = self._map_items(
                        kb_id, source, response.get("items", []), agent_id, policy)
                    nodes.extend(mapped)
                    denied += rejected
                    invalid += malformed
                    if response.get("is_end", True):
                        break
                    cursor = response.get("next_cursor", "")
                    if not cursor or cursor in seen_cursors:
                        partial = True
                        break
                    seen_cursors.add(cursor)
                else:
                    partial = True
        except Exception as exc:
            cached = self._cached(cache_query, agent_id, policy)
            if cached is not None:
                return cached
            raise KnowledgeUnavailable(self._error_code(exc)) from None
        now = datetime.now(timezone.utc).isoformat()
        self._save(cache_query, agent_id, nodes, now)
        return QueryResponse(nodes=nodes, permission="approved", denied_count=denied,
                             invalid_count=invalid, source="ima", stale=False,
                             partial=partial, cached_at=now)

    def _cached_node(self, node_id: str, agent_id: str,
                     policy: AgentPolicy) -> tuple[GatewayNode, str] | None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT cached_at, nodes_json FROM authorized_summary_cache WHERE agent_id=? ORDER BY cached_at DESC",
                (agent_id,),
            ).fetchall()
        for cached_at, encoded in rows:
            for raw in json.loads(encoded):
                if raw.get("id") != node_id:
                    continue
                kb_id = raw.get("metadata", {}).get("knowledge_base_id")
                source = self.sources.get(kb_id)
                if source is None:
                    continue
                node = GatewayNode(**{**raw, "domain": (source["domain"],),
                                      "sensitivity": source.get("sensitivity", "level_0")})
                if check_read_permission(node, agent_id, policy).allowed:
                    return node, cached_at
        return None

    def get_node(self, node_id: str, *, agent_id: str, credential: str) -> QueryResponse:
        policy = self._policy(agent_id, credential)
        authorized = self._cached_node(node_id, agent_id, policy)
        if authorized is None:
            raise KnowledgeUnavailable("node_not_found")
        summary, cached_at = authorized
        if self.adapter is None:
            return QueryResponse(nodes=[summary], permission="approved", denied_count=0,
                                 invalid_count=0, source="ima_cache", stale=True,
                                 partial=True, cached_at=cached_at)
        try:
            media = self.adapter.fetch_media(summary.metadata["media_id"])
            kind, target = self.adapter.media_target(media)
            if kind != "note":
                raise KnowledgeUnavailable("content_unavailable")
            body = self.adapter.fetch_note_content(target)
        except KnowledgeUnavailable:
            raise
        except Exception:
            return QueryResponse(nodes=[summary], permission="approved", denied_count=0,
                                 invalid_count=0, source="ima_cache", stale=True,
                                 partial=True, cached_at=cached_at)
        if not isinstance(body, str):
            raise KnowledgeUnavailable("content_unavailable")
        # Full IMA content is never written to the local summary cache.
        node = replace(summary, body=body)
        return QueryResponse(nodes=[node], permission="approved", denied_count=0,
                             invalid_count=0, source="ima", stale=False,
                             partial=False, cached_at=datetime.now(timezone.utc).isoformat())

    def get_context(self, task: str, *, agent_id: str, credential: str) -> ContextResponse:
        result = self.query_knowledge(task, agent_id=agent_id, credential=credential)
        return ContextResponse(knowledge=result.nodes, experience=[], principles=[])

    def health(self, *, probe: bool = False) -> dict[str, Any]:
        if not self.sources or self.adapter is None:
            with self._connect() as db:
                latest = db.execute("SELECT MAX(cached_at) FROM authorized_summary_cache").fetchone()[0]
            return {"status": "offline_cache" if latest else "not_configured", "source": "ima",
                    "cached_at": latest, "stale": bool(latest)}
        if probe:
            try:
                kb_id = next(iter(self.sources))
                self.adapter.list_items(kb_id, limit=1)
            except Exception as exc:
                message = str(exc).lower()
                status = "auth_required" if "401" in message or "unauthorized" in message else "provider_unavailable"
                return {"status": status, "source": "ima", "stale": True}
            return {"status": "online", "source": "ima", "stale": False}
        return {"status": "configured_unverified", "source": "ima", "stale": False}
