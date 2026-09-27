"""IMA 认知资产写入器。

复用 `integrations/ima.py`（官方 OpenAPI，端点实测见 ADR-008）：
- 写入 = `create_note`（markdown）→ `mount_note_into_knowledge` 挂载到
  `认知资产 CognitiveAssets / <类型双语>` 文件夹路径（ensure_folder_path 幂等）。
- 更新 = `append_note` 追加带时间戳事件（IMA 无覆盖写 —— 平台边界，不是未实现）。
- 删除 = NOT_SUPPORTED（ImaCapabilityError）。

标题携带 cognitive_id（`[KNW-20260915-000123] 标题`）：
这是 IMA 侧去重的关键 —— 检索结果解析标题前缀即可按 cognitive_id 合并。
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import CognitiveAsset

FOLDER_ROOT = "认知资产 CognitiveAssets"


class ImaWriteTransport(Protocol):
    """鸭子类型：integrations.ima.ImaAdapter 满足本协议（测试用假适配器）。"""

    def create_note(self, content: str, *, title: str = "", folder_id: str = "") -> dict[str, Any]: ...

    def mount_note_into_knowledge(
        self, *, knowledge_base_id: str, note_id: str, title: str, folder_id: str = ""
    ) -> dict[str, Any]: ...

    def append_note(self, note_id: str, content: str, *, content_format: int = 1) -> dict[str, Any]: ...

    def ensure_folder_path(self, *, knowledge_base_id: str, segments: list[str] | tuple[str, ...]) -> str: ...


def render_markdown(asset: CognitiveAsset) -> str:
    """渲染认知资产为 markdown。双语标签行 + 元数据块。"""
    zh_label, en_label = asset.type_label
    tag_line = " ".join(f"#{tag.zh} #{tag.en}" for tag in asset.tags if tag.en) or "（无标签）"
    candidate_tags = [tag.zh for tag in asset.tags if tag.is_candidate]
    lines = [
        f"# {asset.title}",
        "",
        asset.statement or "",
        "",
        f"**标签 Tags**: {tag_line}",
        "",
        "---",
        f"- cognitive_id: {asset.cognitive_id}",
        f"- 类型 Type: {zh_label} / {en_label}",
        f"- 版本 Version: v{asset.version}",
        f"- 置信度 Confidence: {asset.confidence:.2f}",
        f"- 来源对象 SourceObject: {asset.source_object_id or 'N/A'}",
    ]
    if asset.relations:
        lines.append("- 关系 Relations:")
        lines.extend(
            f"  - {relation.relation_type} → {relation.target_cognitive_id}" for relation in asset.relations
        )
    if candidate_tags:
        lines.append(f"- 待补英文标签 CandidateTags: {'、'.join(candidate_tags)}")
    lines.append("")
    return "\n".join(lines)


def extract_cognitive_id_from_title(title: str) -> str:
    """从 IMA 条目标题解析 cognitive_id（检索去重用）。无前缀返回空串。"""
    stripped = title.strip()
    if not stripped.startswith("["):
        return ""
    end = stripped.find("]")
    if end <= 1:
        return ""
    return stripped[1:end]


class ImaCognitiveWriter:
    """IMA 侧持久化实现。capability：增 ✅ / 改 = append / 删 ❌。"""

    name = "ima"
    supports_update = False  # 仅追加（append-only），无覆盖写
    supports_delete = False

    def __init__(self, adapter: ImaWriteTransport, knowledge_base_id: str) -> None:
        self._adapter = adapter
        self._knowledge_base_id = knowledge_base_id

    def write(self, asset: CognitiveAsset) -> dict[str, Any]:
        """新建：笔记 + 挂载。返回 {"status": "synced", "ref": note_id, "remote_hash": 本地哈希}。

        远端无内容哈希回读能力（UNKNOWN），以写入成功时的本地哈希代表远端版本。
        """
        if not asset.cognitive_id:
            raise ValueError("asset.cognitive_id 未分配，拒绝写入 IMA")
        zh_label, en_label = asset.type_label
        content = render_markdown(asset)
        created = self._adapter.create_note(content, title=f"[{asset.cognitive_id}] {asset.title}")
        note_id = str((created or {}).get("doc_id") or (created or {}).get("note_id") or "")
        if not note_id:
            raise RuntimeError(f"IMA create_note 未返回 doc_id: {created!r}")
        folder_id = self._adapter.ensure_folder_path(
            knowledge_base_id=self._knowledge_base_id, segments=[FOLDER_ROOT, f"{zh_label} {en_label}"]
        )
        self._adapter.mount_note_into_knowledge(
            knowledge_base_id=self._knowledge_base_id,
            note_id=note_id,
            title=f"[{asset.cognitive_id}] {asset.title}",
            folder_id=folder_id,
        )
        return {"status": "synced", "ref": note_id, "remote_hash": asset.content_hash, "extra": {"folder_id": folder_id}}

    def append_update(self, asset: CognitiveAsset, *, detail: str = "") -> dict[str, Any]:
        """更新 = 追加事件（append-only）。目标笔记 ref 从 asset.ima_ref 取。"""
        if not asset.ima_ref:
            raise ValueError("asset.ima_ref 为空，无法追加更新（应先 write）")
        from datetime import datetime

        event = (
            f"\n## [{datetime.now().strftime('%Y-%m-%d %H:%M')}] 更新 v{asset.version}\n\n"
            f"- 标题：{asset.title}\n"
            f"- 内容：{asset.statement}\n"
            f"- 标签：{' '.join(f'#{t.zh} #{t.en}' for t in asset.tags if t.en) or '（无）'}\n"
            + (f"- 说明：{detail}\n" if detail.strip() else "")
        )
        self._adapter.append_note(asset.ima_ref, event)
        return {"status": "synced", "ref": asset.ima_ref, "remote_hash": asset.content_hash}

    def delete(self, cognitive_id: str) -> None:
        raise NotImplementedError(
            "IMA 官方接口不支持删除（平台边界，见 ADR-008）。"
            "删除语义由本地 tombstone + IMA 侧 IMSDEL 打标表达，须显式走治理流程。"
        )
