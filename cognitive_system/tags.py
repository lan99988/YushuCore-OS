"""中英双语标签注册表。

用户要求：知识库标签一律中英双语，方便使用。
- zh 为规范键（tag identity）；en 必填才算 confirmed。
- 未登记的标签先以 candidate 入库（不阻断写入），与 ADR-008「观察区」治理一致。
- 种子词典覆盖系统高频域（学习/训练/睡眠/恢复/项目/决策/财务…）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import BilingualTag

# 种子词典：zh -> en。只收录系统与用户日常高频域，随时可经 register() 扩充。
SEED_TAGS: dict[str, str] = {
    "知识": "knowledge",
    "概念": "concept",
    "经验": "experience",
    "洞察": "insight",
    "信念": "belief",
    "决策": "decision",
    "学习": "learning",
    "考试": "exam",
    "训练": "training",
    "睡眠": "sleep",
    "恢复": "recovery",
    "健康": "health",
    "营养": "nutrition",
    "项目": "project",
    "任务": "task",
    "效率": "productivity",
    "财务": "finance",
    "阅读": "reading",
    "技术": "technology",
    "工作": "work",
    "生活": "life",
    "情绪": "emotion",
    "习惯": "habit",
    "时间管理": "time-management",
    "深度工作": "deep-work",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TagRegistry:
    """双语标签注册表，落 `cognitive_tag_registry` 表（经 store 注入回调）。

    `lookup(zh)` 返回注册表中该标签的 BilingualTag；未登记则返回 candidate。
    `normalize(tags)` 逐个补全英文并回写注册表。
    """

    def __init__(self, *, loader: dict[str, str] | None = None, saver=None) -> None:
        self._zh_to_en: dict[str, str] = dict(SEED_TAGS)
        if loader:
            self._zh_to_en.update(loader)
        self._saver = saver

    # ---------------------------------------------------------------- 查询

    def lookup(self, zh: str) -> BilingualTag:
        key = zh.strip()
        en = self._zh_to_en.get(key, "")
        return BilingualTag(zh=key, en=en, status="confirmed" if en else "candidate")

    def reverse(self, en: str) -> BilingualTag | None:
        key = en.strip().casefold()
        for zh, candidate_en in self._zh_to_en.items():
            if candidate_en.casefold() == key:
                return BilingualTag(zh=zh, en=candidate_en, status="confirmed")
        return None

    # ---------------------------------------------------------------- 登记

    def register(self, zh: str, en: str) -> BilingualTag:
        """登记/补全一条双语标签（confirmed）。"""
        key = zh.strip()
        if not key:
            raise ValueError("标签中文（zh）不能为空")
        cleaned_en = en.strip()
        if not cleaned_en:
            raise ValueError("标签英文（en）不能为空 —— 双语标签体系要求中英文齐备")
        self._zh_to_en[key] = cleaned_en
        if self._saver is not None:
            self._saver(key, cleaned_en, "confirmed")
        return BilingualTag(zh=key, en=cleaned_en, status="confirmed")

    def record_candidate(self, zh: str) -> None:
        """未登记标签入候选区（不阻断主流程）。"""
        key = zh.strip()
        if key and key not in self._zh_to_en and self._saver is not None:
            self._saver(key, "", "candidate")

    # ---------------------------------------------------------------- 归一化

    def normalize(self, tags: tuple[BilingualTag, ...] | tuple[str, ...]) -> tuple[BilingualTag, ...]:
        """把任意标签输入归一化为双语标签；能补英文的补英文，补不了的进候选区。"""
        normalized: list[BilingualTag] = []
        seen: set[str] = set()
        for tag in tags:
            if isinstance(tag, BilingualTag):
                resolved = self.lookup(tag.zh)
                if tag.en and not resolved.en:
                    resolved = self.register(tag.zh, tag.en)
                elif tag.en and tag.en != resolved.en:
                    # 与注册表冲突时以注册表为准（保证跨库一致）
                    resolved = resolved
            else:
                resolved = self.lookup(str(tag))
            if resolved.is_candidate:
                self.record_candidate(resolved.zh)
            if resolved.zh not in seen:
                seen.add(resolved.zh)
                normalized.append(resolved)
        return tuple(normalized)
