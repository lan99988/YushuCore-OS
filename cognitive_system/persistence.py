"""Cognitive Persistence Layer（计划书第九/二十六/三十六/三十七节）。

- 业务层只面对 CognitiveAsset；「怎么写 IMA / 怎么写飞书」由本层派发。
- Persistence Policy 可切换 dual / ima / feishu —— 最终主库决策不改业务代码。
- 单库失败：对象照常存在，进入 retry queue；不要求用户重输。
- 最终一致性优先：不追求事务级双写。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .ids import CognitiveIdAllocator
from .models import CognitiveAsset, SYNC_STATES
from .store import CognitiveStore, compute_sync_state
from .tags import TagRegistry

VALID_TARGETS = ("ima", "feishu")


@dataclass(frozen=True)
class PersistencePolicy:
    """知识持久化策略（计划书第二十六节的决策接口）。"""

    primary: str = "dual"  # dual | ima | feishu

    @property
    def targets(self) -> tuple[str, ...]:
        if self.primary == "ima":
            return ("ima",)
        if self.primary == "feishu":
            return ("feishu",)
        if self.primary == "dual":
            return ("ima", "feishu")
        raise ValueError(f"非法持久化策略: {self.primary}")


class TargetWriter(Protocol):
    name: str

    def write(self, asset: CognitiveAsset) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WriteResult:
    target: str
    status: str  # synced | failed
    ref: str = ""
    error: str = ""


@dataclass(frozen=True)
class PersistOutcome:
    cognitive_id: str
    created: bool
    sync_state: str
    results: tuple[WriteResult, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cognitive_id": self.cognitive_id,
            "created": self.created,
            "sync_state": self.sync_state,
            "results": [
                {"target": item.target, "status": item.status, "ref": item.ref, "error": item.error}
                for item in self.results
            ],
        }


class CognitivePersistenceLayer:
    """认知资产持久化门面。"""

    def __init__(
        self,
        store: CognitiveStore,
        *,
        writers: dict[str, TargetWriter] | None = None,
        policy: PersistencePolicy | None = None,
        tag_registry: TagRegistry | None = None,
        allocator: CognitiveIdAllocator | None = None,
    ) -> None:
        self._store = store
        self._writers = dict(writers or {})
        self._policy = policy or PersistencePolicy()
        self._registry = tag_registry or TagRegistry(
            loader=store.load_tags(), saver=store.upsert_tag
        )
        self._allocator = allocator or CognitiveIdAllocator(
            sequence_fn=store.next_sequence
        )

    # ---------------------------------------------------------------- 属性

    @property
    def policy(self) -> PersistencePolicy:
        return self._policy

    def set_policy(self, policy: PersistencePolicy) -> None:
        """切换主库策略（IMA First / Feishu First / Hybrid）。"""
        self._policy = policy

    # ---------------------------------------------------------------- 写入

    def persist(self, asset: CognitiveAsset) -> PersistOutcome:
        """分配 cognitive_id → 落本地库 → 按 policy 派发双写 → 记状态/重试。"""
        if asset.cognitive_type not in ("source", "note", "experience", "knowledge", "concept", "insight", "belief", "decision"):
            raise ValueError(f"非法认知类型: {asset.cognitive_type}")
        existing = None
        if asset.cognitive_id:
            existing = self._store.get_asset(asset.cognitive_id)
        created = existing is None

        # 幂等：同 cognitive_id 重复写入不产生第二条资产（计划书测试要求 Duplicate）
        if not created and existing is not None:
            if (
                existing.title == asset.title
                and existing.statement == asset.statement
                and existing.tags == asset.tags
                and existing.relations == asset.relations
            ):
                return self._dispatch_targets(existing, created=False)
            # 内容补充（如新增关系）：合并进现有资产，不新增条目
            asset = existing.with_updates(
                title=asset.title, statement=asset.statement,
                tags=self._registry.normalize(asset.tags), relations=asset.relations,
                confidence=asset.confidence,
            )

        asset = asset.with_updates(tags=self._registry.normalize(asset.tags))
        if not asset.cognitive_id:
            asset = asset.with_updates(cognitive_id=self._allocator.allocate(asset.cognitive_type))
        asset = self._store.save_asset(asset)
        return self._dispatch_targets(asset, created=created)

    def _dispatch_targets(self, asset: CognitiveAsset, *, created: bool) -> PersistOutcome:
        results: list[WriteResult] = []
        for target in self._policy.targets:
            writer = self._writers.get(target)
            if writer is None:
                # 未接入的通道：保持 pending，不入重试队列（配置缺失不是瞬态故障）
                results.append(WriteResult(target=target, status="failed", error="writer 未配置"))
                continue
            try:
                payload = writer.write(asset)
                status = str(payload.get("status", "synced"))
                ref = str(payload.get("ref", ""))
                self._store.update_persistence(
                    asset.cognitive_id, target=target, status="synced", ref=ref,
                    remote_hash=str(payload.get("remote_hash", "")),
                )
                self._store.append_sync_log(asset.cognitive_id, target, "write", {"ref": ref})
                self._store.mark_retry(asset.cognitive_id, target, status="done")
                results.append(WriteResult(target=target, status="synced", ref=ref))
            except Exception as exc:  # noqa: BLE001 —— 单库失败不阻断另一库
                error = str(exc)
                self._store.update_persistence(asset.cognitive_id, target=target, status="failed")
                self._store.enqueue_retry(asset.cognitive_id, target, error)
                self._store.append_sync_log(asset.cognitive_id, target, "write_failed", {"error": error[:300]})
                results.append(WriteResult(target=target, status="failed", error=error))
        updated = self._store.get_asset(asset.cognitive_id)
        assert updated is not None
        return PersistOutcome(
            cognitive_id=updated.cognitive_id,
            created=created,
            sync_state=updated.sync_state,
            results=tuple(results),
        )

    # ---------------------------------------------------------------- 更新与冲突

    def update_content(
        self,
        cognitive_id: str,
        *,
        title: str | None = None,
        statement: str | None = None,
        tags: tuple[Any, ...] | None = None,
        detail: str = "",
    ) -> PersistOutcome:
        """内容变更：版本 +1 → IMA 追加事件 / 飞书真更新。"""
        asset = self._store.get_asset(cognitive_id)
        if asset is None:
            raise KeyError(f"认知资产不存在: {cognitive_id}")
        updated = asset.bump_version(
            title=title, statement=statement,
            tags=self._registry.normalize(tags) if tags is not None else None,
        )
        self._store.save_asset(updated)
        results: list[WriteResult] = []
        for target in self._policy.targets:
            writer = self._writers.get(target)
            if writer is None:
                results.append(WriteResult(target=target, status="failed", error="writer 未配置"))
                continue
            try:
                if target == "ima":
                    payload = writer.append_update(updated, detail=detail)  # type: ignore[attr-defined]
                elif hasattr(writer, "update"):
                    payload = writer.update(updated)  # type: ignore[attr-defined]
                else:
                    payload = writer.write(updated)
                self._store.update_persistence(
                    cognitive_id, target=target, status="synced",
                    ref=str(payload.get("ref", "")),
                    remote_hash=str(payload.get("remote_hash", "")),
                )
                self._store.append_sync_log(cognitive_id, target, "update", {"version": updated.version})
                results.append(WriteResult(target=target, status="synced", ref=str(payload.get("ref", ""))))
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                self._store.update_persistence(cognitive_id, target=target, status="failed")
                self._store.enqueue_retry(cognitive_id, target, error)
                results.append(WriteResult(target=target, status="failed", error=error))
        refreshed = self._store.get_asset(cognitive_id)
        assert refreshed is not None
        return PersistOutcome(
            cognitive_id=cognitive_id,
            created=False,
            sync_state=refreshed.sync_state,
            results=tuple(results),
        )

    def detect_remote_conflict(self, cognitive_id: str, *, target: str, remote_hash: str) -> bool:
        """远端内容哈希与本地不一致 → CONTENT_CONFLICT（不自动覆盖，计划书第二十五节）。"""
        if target not in VALID_TARGETS:
            raise ValueError(f"非法持久化目标: {target}")
        asset = self._store.get_asset(cognitive_id)
        if asset is None:
            raise KeyError(f"认知资产不存在: {cognitive_id}")
        if remote_hash and remote_hash != asset.content_hash:
            self._store.update_persistence(
                cognitive_id, target=target, status="conflict", remote_hash=remote_hash
            )
            self._store.append_sync_log(cognitive_id, target, "conflict", {"remote_hash": remote_hash})
            return True
        return False

    # ---------------------------------------------------------------- 重试

    def retry_pending(self, *, limit: int = 20) -> list[PersistOutcome]:
        """处理重试队列。仅重试**瞬态**失败；writer 未配置的持续失败会被标记 dead。"""
        outcomes: list[PersistOutcome] = []
        for entry in self._store.open_retries(limit=limit):
            target = str(entry["target"])
            cognitive_id = str(entry["cognitive_id"])
            writer = self._writers.get(target)
            asset = self._store.get_asset(cognitive_id)
            if asset is None:
                self._store.mark_retry(cognitive_id, target, status="dead")
                continue
            if writer is None:
                self._store.mark_retry(cognitive_id, target, status="dead")
                continue
            try:
                payload = writer.write(asset)
                self._store.update_persistence(
                    cognitive_id, target=target, status="synced",
                    ref=str(payload.get("ref", "")),
                    remote_hash=str(payload.get("remote_hash", "")),
                )
                self._store.mark_retry(cognitive_id, target, status="done")
                self._store.append_sync_log(cognitive_id, target, "retry_success", {})
            except Exception as exc:  # noqa: BLE001
                self._store.enqueue_retry(cognitive_id, target, str(exc))
            refreshed = self._store.get_asset(cognitive_id)
            assert refreshed is not None
            outcomes.append(
                PersistOutcome(
                    cognitive_id=cognitive_id,
                    created=False,
                    sync_state=refreshed.sync_state,
                )
            )
        return outcomes
