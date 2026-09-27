"""项目名解析（P1-8 修复）。

职责：把正文里出现的已登记项目名/别名匹配为 `projects`（多值）。
- **数据源是配置**（`config/projects.yaml`），不是代码常量 —— 与 DomainRegistry 同一条纪律：
  项目清单属于用户资产，代码不得硬编码。
- 无配置 / 无命中 → 返回空（**不编造项目**）。
- 只读、无网络。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ScoredItem

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_RELATIVE = Path("config") / "projects.yaml"


@dataclass(frozen=True)
class ProjectRecord:
    name: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("项目名不能为空")


@dataclass
class ProjectResolver:
    """项目名匹配器。`match` 保持确定性：同输入同输出。"""

    projects: tuple[ProjectRecord, ...] = ()
    confidence_base: float = 0.7

    def __post_init__(self) -> None:
        # 别名 → 规范名（大小写不敏感，便于匹配英文项目名）
        index: dict[str, str] = {}
        for record in self.projects:
            for token in (record.name, *record.aliases):
                cleaned = token.strip()
                if cleaned:
                    index.setdefault(cleaned.casefold(), record.name)
        self._index: dict[str, str] = index
        # 长名优先，避免「项目 A」被「A」抢先匹配
        self._tokens: tuple[str, ...] = tuple(
            sorted(index.keys(), key=len, reverse=True)
        )

    @property
    def is_empty(self) -> bool:
        return not self._tokens

    def resolve(self, *, title: str, text: str) -> tuple[ScoredItem, ...]:
        haystack = f"{title}\n{text}"
        folded = haystack.casefold()
        hits: list[ScoredItem] = []
        seen: set[str] = set()
        for token in self._tokens:
            index = folded.find(token)
            if index < 0:
                continue
            canonical = self._index[token]
            if canonical in seen:
                continue
            seen.add(canonical)
            snippet = haystack[max(0, index - 6) : index + len(token) + 6].replace("\n", " ").strip()
            hits.append(
                ScoredItem(
                    label=canonical,
                    confidence=min(0.95, self.confidence_base + 0.05 * min(len(token), 4)),
                    evidence=(snippet,),
                    reason=f"正文命中项目标识「{token}」",
                )
            )
        return tuple(hits)

    @classmethod
    def from_config(cls, path: str | Path | None = None) -> "ProjectResolver":
        """从 `config/projects.yaml` 读取。文件缺失 → 空解析器（不产出、不报错）。"""
        config_path = Path(path) if path else PROJECT_ROOT / DEFAULT_CONFIG_RELATIVE
        if not config_path.is_file():
            return cls(projects=())
        import yaml

        payload: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        records: list[ProjectRecord] = []
        for item in payload.get("projects") or []:
            if isinstance(item, str):
                records.append(ProjectRecord(name=item.strip()))
                continue
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            aliases = tuple(str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip())
            records.append(ProjectRecord(name=name, aliases=aliases))
        return cls(projects=tuple(records))
