"""IMA（腾讯 ima.qq.com）集成适配器 —— 官方 OpenAPI 通道。

设计依据：
- `07_系统文档（Docs）/ADR/ADR-008_IMA_Information_Layer_Integration.md`
- 官方 skill 包 `ima-skills-1.1.10`
  （https://app-dl.ima.qq.com/skills/ima-skills-<版本>.zip）
  内的 `knowledge-base/references/api.md` 与 `notes/references/api.md`

三条硬约束（实测，见 ADR-008）：
1. IMA 官方接口**没有删除**。本适配器不提供 `delete_*`，
   调用时应显式抛出 `ImaCapabilityError`，**不得用其他通道硬凑**。
   「改」则**部分存在**：只有「原地改名 / 追加」类，**没有覆盖写**
   （`rename_knowledge` / `rename_note` / `rename_notebook` / `append_doc`）。
2. 「改 / 删」以 **append-only** 表达：新增一节带时间戳的记录，不改旧行。
3. 不实现 cookie 逆向通道（理由见 ADR-008「拒绝 B」）。

## 端点确信度：已全部在真实账号上验证（2026-09-14）

验证脚本：`09_临时文件（Temp）/probe_ima_endpoints.py`、`probe_ima_endpoints2.py`。
逐端点实测结果：

| 端点 | 实测 |
| --- | --- |
| `wiki/v1/get_addable_knowledge_base_list` | OK，返回 `addable_knowledge_base_list` |
| `wiki/v1/get_knowledge_base` | OK，返回 `infos`（map<id, KnowledgeBaseInfo>） |
| `wiki/v1/get_knowledge_list` | OK，返回 `knowledge_list` / `is_end` / `next_cursor` / `current_path` |
| `wiki/v1/search_knowledge_base` | OK，返回 **`info_list`**，条目字段为 **`kb_id` / `kb_name`** |
| `wiki/v1/search_knowledge` | OK，返回 `info_list` |
| `wiki/v1/check_repeated_names` | OK，返回 `results[].is_repeated` |
| `wiki/v1/get_media_info` | OK，返回 `media_type` + `url_info{url, headers}` |
| `note/v1/list_notebook` | OK，返回 `note_folder_infos` |
| `note/v1/list_note` | OK，返回 `note_book_list` |
| `note/v1/search_note` | OK，返回 `search_note_infos` |
| `note/v1/list_docs` | **HTTP 404 —— 该路径不存在**（此前误推断，已删除） |

### 两处「文档与实现不符」，一律以真实响应为准

1. `search_knowledge_base` 的条目字段是 `kb_id` / `kb_name`，而官方 api.md 的
   `SearchedKnowledgeBaseInfo` 表格写作 `id` / `name`。**文档有误**，本适配器按真实响应解析。
2. `search_note` 实测必须携带 `query_info`（即使只按标题检索），否则服务端返回
   `code=100001 ListNoteBook param is error`。官方文档把 `query_info` 标为「否」，
   与实现不符。本适配器**始终**发送 `query_info`。

### 写入类端点的真实验证结论（2026-09-15 实测）

| 能力 | 端点 | 实测结果 |
| --- | --- | --- |
| 增·笔记 | `note/v1/import_doc` | ✅ 成功（真实建笔记；`title` 参数被服务端接受） |
| 改·追加 | `note/v1/append_doc` | ✅ 成功（追加后回读确认，135→167 字） |
| 增·文件夹 | `wiki/v1/create_folder` | ✅ 成功（**未文档化**；返回 `media_id`，形如 `folder_xxx`） |
| 改·重命名 | `wiki/v1/rename_knowledge` | ✅ 成功（**未文档化**；目录中名称真实变更） |
| 增·网页 | `wiki/v1/import_urls` | ✅ 成功（**但必须传真实根目录 folder_id**，见下） |
| 移动条目 | `wiki/v1/move_knowledge` | ❌ **疑为服务端空壳**：字段名 `media_ids`（`[]string`）、元素形状、`src≠dst` 均已实测排除，`move_results` 仍恒为空 | 见 `move_knowledge()` 详注 |
| 建知识库 | `wiki/v1/create_knowledge_base` | ✅ **端到端验证成功**（**未文档化**；必填 `name` + `type`，返回 `{"id", "name"}`） |
| 增·笔记挂载 | `wiki/v1/add_knowledge` + `media_type=11` | ✅ **成功**（`note_info.content_id=<note_id>`；把笔记挂进知识库**文件夹路径**，回读 `current_path` 深度 3） |
| 建笔记本 | `note/v1/add_notebook` | ✅ **成功**（**未文档化**；字段名是 **`folder_name`**，返回 `{"folder_id","folder_name"}`） |
| 改·笔记本名 | `note/v1/rename_notebook` | ✅ **成功**（**未文档化**；字段 `folder_id` + **`new_folder_name`**；⚠️ 不带新名会**清空**名字） |
| 改·笔记标题 | `note/v1/rename_note` | ✅ **成功**（**未文档化**；字段 `note_id` + `title`，原地改名） |
| 批量改笔记 | `note/v1/update_note` | ❓ **端点已注册**（`Updates` 为数组，1–100 项），语义未探，未接入 |
| 删 | `delete_knowledge`/`delete_media`/`remove_knowledge`/`delete_knowledge_base`/`delete_folder`/`delete_doc`/`delete_note`/`delete_doc`/`batch_delete_note`/`delete_notebook`/`remove_notebook`/`trash_doc`（12 条） | ❌ **全部 HTTP 404，官方 API 无删除能力** |

### ⚠️ 官方文档的第三处错误：根目录 folder_id

api.md「文件夹说明」称「**根目录的 folder_id 等于 knowledge_base_id**」——**实测错误**。
用 `knowledge_base_id` 当 `folder_id` 调 `import_urls`，服务端返回
`code=222000 文件夹不存在`。真实根目录 id 来自 `get_knowledge_list` 的
`current_path[0].folder_id`，与 `knowledge_base_id` 是两个不同的值。
本适配器的 `import_urls` 会**自动解析**真实根目录（见 `root_folder_id()`）。

### 未文档化端点的发现方法（可复现）

网关能区分「已注册路由」与「未注册路径」：编造路径返回 **HTTP 404**，
已注册但缺参数的路径返回 **`code=51`** 并附带 protobuf 校验消息
（形如 `invalid RenameKnowledgeReq.Name: value length must be between 1 and 255 runes`）。
错误消息会**逐字段暴露参数名与约束**，因此可安全枚举签名——
只要用不存在的 id 兜底，业务层就会先失败，不会产生真实变更。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
from typing import Any, Callable, Protocol
import urllib.error
import urllib.request

from .base import AdapterError, IntegrationAdapter
from .settings import ima_credentials, resolve_network_mode

BASE_URL = "https://ima.qq.com"
REQUEST_TIMEOUT_SECONDS = 30

DEFAULT_ENDPOINTS: dict[str, str] = {
    # ---- 知识库（wiki/v1）----
    "search_knowledge_base": "/openapi/wiki/v1/search_knowledge_base",
    "get_knowledge_base": "/openapi/wiki/v1/get_knowledge_base",
    "get_knowledge_list": "/openapi/wiki/v1/get_knowledge_list",
    "search_knowledge": "/openapi/wiki/v1/search_knowledge",
    "get_media_info": "/openapi/wiki/v1/get_media_info",
    "get_addable_knowledge_base_list": "/openapi/wiki/v1/get_addable_knowledge_base_list",
    "check_repeated_names": "/openapi/wiki/v1/check_repeated_names",
    "import_urls": "/openapi/wiki/v1/import_urls",
    "create_media": "/openapi/wiki/v1/create_media",
    "add_knowledge": "/openapi/wiki/v1/add_knowledge",
    # ---- 未文档化但**实测路由存在**的端点（发现方法见模块 docstring）----
    "create_folder": "/openapi/wiki/v1/create_folder",
    "rename_knowledge": "/openapi/wiki/v1/rename_knowledge",
    "move_knowledge": "/openapi/wiki/v1/move_knowledge",
    "create_knowledge_base": "/openapi/wiki/v1/create_knowledge_base",
    # ---- 笔记（note/v1）—— append-only 的载体 ----
    "note_import_doc": "/openapi/note/v1/import_doc",
    "note_append_doc": "/openapi/note/v1/append_doc",
    "note_get_doc_content": "/openapi/note/v1/get_doc_content",
    "note_list_note": "/openapi/note/v1/list_note",
    "note_list_notebook": "/openapi/note/v1/list_notebook",
    "note_search_note": "/openapi/note/v1/search_note",
    # ↓ 2026-09-15 探得：**未文档化但真实存在**（官方技能包端点集里没有）
    "note_add_notebook": "/openapi/note/v1/add_notebook",
    "note_rename_notebook": "/openapi/note/v1/rename_notebook",
    "note_rename_note": "/openapi/note/v1/rename_note",
}

# ---------------------------------------------------------------- MediaType

# 官方枚举（api.md「MediaType（媒体类型枚举）」表，实测与文档一致）
MEDIA_TYPE_PDF = 1
MEDIA_TYPE_WEBPAGE = 2  # 网页：直接 add_knowledge，web_info.content_id=<url>
MEDIA_TYPE_WORD = 3
MEDIA_TYPE_PPT = 4
MEDIA_TYPE_EXCEL = 5
MEDIA_TYPE_WECHAT_ARTICLE = 6  # 微信公众号文章：URL 匹配 mp.weixin.qq.com/s
MEDIA_TYPE_MARKDOWN = 7
MEDIA_TYPE_IMAGE = 9
MEDIA_TYPE_NOTE = 11  # 笔记：note_info.content_id=<doc_id>
MEDIA_TYPE_AI_SESSION = 12  # AI 会话：session_info.content_id=<session_id>
MEDIA_TYPE_TXT = 13
MEDIA_TYPE_XMIND = 14
MEDIA_TYPE_AUDIO = 15  # 录音，额外限制：最长 2 小时
MEDIA_TYPE_VIDEO = 16  # 视频解析：**不支持经 skill 添加**，仅 ima 桌面端
MEDIA_TYPE_HTML = 20
MEDIA_TYPE_EPUB = 21
# 文件夹。**不在官方枚举表里**，2026-09-15 实测：`get_knowledge_list` 里的文件夹条目
# 返回 `media_type=99`，且其 media_id 形如 `folder_xxx`。
MEDIA_TYPE_FOLDER = 99

# 具名别名（旧键名保留，向后兼容）
MEDIA_TYPE: dict[str, int] = {
    "pdf": MEDIA_TYPE_PDF,
    "webpage": MEDIA_TYPE_WEBPAGE,
    "word": MEDIA_TYPE_WORD,
    "ppt": MEDIA_TYPE_PPT,
    "excel": MEDIA_TYPE_EXCEL,
    "wechat": MEDIA_TYPE_WECHAT_ARTICLE,
    "markdown": MEDIA_TYPE_MARKDOWN,
    "img": MEDIA_TYPE_IMAGE,
    "note": MEDIA_TYPE_NOTE,
    "ai_session": MEDIA_TYPE_AI_SESSION,
    "txt": MEDIA_TYPE_TXT,
    "xmind": MEDIA_TYPE_XMIND,
    "audio": MEDIA_TYPE_AUDIO,
    "html": MEDIA_TYPE_HTML,
    "epub": MEDIA_TYPE_EPUB,
}

# 扩展名 → MIME。**找不到对照表时拒绝上传，不猜测**（官方 preflight-check.cjs 同规则）。
EXT_TO_MIME: dict[str, str] = {
    # 1 PDF
    "pdf": "application/pdf",
    # 3 Word
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # 4 PPT
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # 5 Excel / CSV
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    # 7 Markdown
    "md": "text/markdown",
    "markdown": "text/markdown",
    # 9 图片
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    # 13 TXT
    "txt": "text/plain",
    # 14 Xmind
    "xmind": "application/x-xmind",
    # 15 录音
    "mp3": "audio/mpeg",
    "m4a": "audio/x-m4a",
    "wav": "audio/wav",
    "aac": "audio/aac",
    # 20 HTML
    "html": "text/html",
    "htm": "text/html",
    # 21 EPUB
    "epub": "application/epub+zip",
}

# 扩展名 → MediaType。用于上传前的同名检查与大小校验。
# 注意：网页(2)/微信公众号(6)/笔记(11)/AI会话(12)/视频(16) 无对应扩展名，
# 因此不出现在本表中（它们只能经 add_knowledge 的 *_info 字段或 import_urls 添加）。
EXT_TO_MEDIA_TYPE: dict[str, int] = {
    "pdf": MEDIA_TYPE_PDF,
    "doc": MEDIA_TYPE_WORD,
    "docx": MEDIA_TYPE_WORD,
    "ppt": MEDIA_TYPE_PPT,
    "pptx": MEDIA_TYPE_PPT,
    "xls": MEDIA_TYPE_EXCEL,
    "xlsx": MEDIA_TYPE_EXCEL,
    "csv": MEDIA_TYPE_EXCEL,
    "md": MEDIA_TYPE_MARKDOWN,
    "markdown": MEDIA_TYPE_MARKDOWN,
    "png": MEDIA_TYPE_IMAGE,
    "jpg": MEDIA_TYPE_IMAGE,
    "jpeg": MEDIA_TYPE_IMAGE,
    "webp": MEDIA_TYPE_IMAGE,
    "txt": MEDIA_TYPE_TXT,
    "xmind": MEDIA_TYPE_XMIND,
    "mp3": MEDIA_TYPE_AUDIO,
    "m4a": MEDIA_TYPE_AUDIO,
    "wav": MEDIA_TYPE_AUDIO,
    "aac": MEDIA_TYPE_AUDIO,
    "html": MEDIA_TYPE_HTML,
    "htm": MEDIA_TYPE_HTML,
    "epub": MEDIA_TYPE_EPUB,
}

# 官方「文件大小限制」表。未列出的媒体类型按 200 MB 兜底。
SIZE_LIMIT_10MB = 10 * 1024 * 1024
SIZE_LIMIT_30MB = 30 * 1024 * 1024
SIZE_LIMIT_50MB = 50 * 1024 * 1024
DEFAULT_SIZE_LIMIT = 200 * 1024 * 1024

SIZE_LIMITS_BYTES: dict[int, int] = {
    MEDIA_TYPE_EXCEL: SIZE_LIMIT_10MB,  # 5
    MEDIA_TYPE_TXT: SIZE_LIMIT_10MB,  # 13
    MEDIA_TYPE_XMIND: SIZE_LIMIT_10MB,  # 14
    MEDIA_TYPE_MARKDOWN: SIZE_LIMIT_10MB,  # 7
    MEDIA_TYPE_HTML: SIZE_LIMIT_10MB,  # 20
    MEDIA_TYPE_IMAGE: SIZE_LIMIT_30MB,  # 9
    MEDIA_TYPE_EPUB: SIZE_LIMIT_50MB,  # 21
}


def size_limit_for(media_type: int) -> int:
    """返回指定 MediaType 的官方大小上限（字节）。未列出者按 200 MB 兜底。"""
    return SIZE_LIMITS_BYTES.get(media_type, DEFAULT_SIZE_LIMIT)


# ---------------------------------------------------------------- ContentFormat

CONTENT_FORMAT_PLAINTEXT = 0  # 读笔记时官方推荐
CONTENT_FORMAT_MARKDOWN = 1  # 写笔记时官方**仅**支持此值
CONTENT_FORMAT_JSON = 2

# 解析状态。数值来自一次真实响应观测（`media_state: 2` 且 `parse_progress: 100` 表示已解析），
# 未经多态验证，故只暴露最小判据，不做全枚举映射。
MEDIA_STATE_PARSED = 2

# 各端点 limit 上限（官方文档声明）
IMPORT_URLS_BATCH_LIMIT = 10  # import_urls 单次 URL 数
SEARCH_KB_LIMIT_MAX = 20  # search_knowledge_base
SEARCH_KB_LIMIT_MIN = 1
WIKI_LIST_LIMIT_MAX = 50  # get_knowledge_list / get_addable_knowledge_base_list
NOTE_LIST_LIMIT_MAX = 20  # list_note / list_notebook（0 < limit ≤ 20）
GET_KB_IDS_LIMIT_MAX = 20  # get_knowledge_base
CHECK_REPEATED_NAMES_LIMIT_MAX = 2000  # check_repeated_names
SEARCH_NOTE_SPAN_MAX = 20  # search_note: end - start ≤ 20

# create_knowledge_base 的 type 枚举（2026-09-15 由服务端校验消息实测得到）。
# 原文：invalid CreateKnowledgeBaseReq.Type: value must be in list
#       [KBT_MINE_KB KBT_SHARED_KB KBT_SUBSCRIBED_CREATE_KB]
KB_TYPES: frozenset[str] = frozenset(
    {"KBT_MINE_KB", "KBT_SHARED_KB", "KBT_SUBSCRIBED_CREATE_KB"}
)

# 「待删」标记（改名方案）。只用字母/数字/连字符 —— 括号类符号在客户端搜索中的
# 处理方式未经实测，刻意回避。形如：IMSDEL-20260915a3f9-原标题
DELETION_MARKER = "IMSDEL"
_DELETION_MARK_RE = re.compile(rf"^{DELETION_MARKER}-[0-9a-f]{{12}}-")
_DELETION_BATCH_RE = re.compile(r"^[0-9]{8}[0-9a-f]{4}$")


class ImaCapabilityError(AdapterError):
    """请求了 IMA 平台不具备的能力。**这是平台边界，不是未实现。**"""


def _validate_range(value: int, *, low: int, high: int, what: str) -> int:
    """区间校验。越界即抛错，不做静默钳位——静默钳位会掩盖调用方的误解。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{what} 必须是整数，收到 {type(value).__name__}")
    if value < low or value > high:
        raise ValueError(f"{what} 越界：{value}（官方允许 {low} ~ {high}）")
    return value


class ImaTransport(Protocol):
    def __call__(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class UrllibImaTransport:
    """纯标准库 HTTP 传输。凭证只作为请求头发往 ima.qq.com，不落任何日志。

    `skill_version`：官方 `ima_api.cjs` 会额外发送
    `ima-openapi-ctx: skill_version=<ver>`。实测**并非鉴权必需**
    （不发送该头时，正确凭证依然可用），故默认不发送（None），需要时显式传入。
    """

    client_id: str
    api_key: str
    base_url: str = BASE_URL
    timeout: int = REQUEST_TIMEOUT_SECONDS
    opener: Callable[..., Any] | None = None
    skill_version: str | None = None

    def __call__(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not path.startswith("/"):
            raise AdapterError(f"apiPath 必须以 / 开头: {path!r}")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "ima-openapi-clientid": self.client_id,
            "ima-openapi-apikey": self.api_key,
        }
        if self.skill_version:
            headers["ima-openapi-ctx"] = f"skill_version={self.skill_version}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers=headers,
        )
        opener = self.opener or urllib.request.urlopen
        try:
            with opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise AdapterError(f"IMA 请求失败 HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AdapterError(f"IMA 网络不可达 {path}: {exc.reason}") from exc
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise AdapterError(f"IMA 返回非 JSON {path}: {raw[:200]}") from exc
        if not isinstance(decoded, dict):
            raise AdapterError(f"IMA 返回结构异常 {path}: {type(decoded).__name__}")
        code = decoded.get("code")
        if code not in (None, 0):
            raise AdapterError(f"IMA 业务错误 code={code} msg={decoded.get('msg')!r} path={path}")
        data = decoded.get("data")
        return data if isinstance(data, dict) else decoded


class ImaAdapter(IntegrationAdapter):
    """IMA 只读拉取 + append-only 写入适配器。

    能力声明见 `config/integrations.yaml`：`read: true, write: true, delete: false`。
    """

    name = "ima"
    supports_delete = False
    supports_update = False

    def __init__(
        self,
        *,
        transport: ImaTransport | None = None,
        network_mode: str | None = None,
        endpoints: dict[str, str] | None = None,
    ) -> None:
        mode = (network_mode or resolve_network_mode(self.name)).upper()
        super().__init__(network_mode=mode)
        self.endpoints = dict(DEFAULT_ENDPOINTS)
        if endpoints:
            self.endpoints.update(endpoints)
        if transport is not None:
            self._transport: ImaTransport = transport
        else:
            client_id, api_key = ima_credentials()
            self._transport = UrllibImaTransport(client_id=client_id, api_key=api_key)

    # ------------------------------------------------------------------ 内部

    def _call(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_assist_or_sync()
        path = self.endpoints.get(key)
        if path is None:
            raise AdapterError(f"未声明的端点: {key}")
        self._record(key)
        return self._transport(path, payload)

    @staticmethod
    def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """从响应中取出条目列表。

        `info_list` 优先：这是 `search_knowledge_base` / `search_knowledge` 的
        真实字段名（2026-09-14 实测）。`knowledge_list` 是 `get_knowledge_list` 的
        字段名。其余键名为历史兜底，保留以容忍服务端字段微调。
        """
        for key in ("info_list", "knowledge_list", "search_note_infos", "note_book_list", "items", "list", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    # ------------------------------------------------------------------ 读：知识库

    def search_knowledge_bases(
        self, query: str = "", *, cursor: str = "", limit: int = SEARCH_KB_LIMIT_MAX
    ) -> list[dict[str, Any]]:
        """搜索知识库列表。

        真实条目字段为 `kb_id` / `kb_name`（**不是**官方文档写的 `id` / `name`）。
        另会附带 `member_count` / `content_count` / `description` / `creator` /
        `role_type` / `base_type` 等扩展字段。
        """
        _validate_range(limit, low=SEARCH_KB_LIMIT_MIN, high=SEARCH_KB_LIMIT_MAX, what="search_knowledge_base 的 limit")
        payload = self._call("search_knowledge_base", {"query": query, "cursor": cursor, "limit": limit})
        return self._items(payload)

    def get_knowledge_base(self, ids: list[str]) -> dict[str, Any]:
        """按 ID 批量取知识库信息。返回 `{"infos": {<id>: KnowledgeBaseInfo}}`。"""
        cleaned = [str(i).strip() for i in ids if str(i).strip()]
        if not cleaned:
            raise ValueError("ids 不能为空")
        if len(cleaned) > GET_KB_IDS_LIMIT_MAX:
            raise ValueError(f"单次最多 {GET_KB_IDS_LIMIT_MAX} 个知识库 ID，当前 {len(cleaned)} 个")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("ids 中存在重复项（官方要求不重复）")
        return self._call("get_knowledge_base", {"ids": cleaned})

    def addable_knowledge_bases(
        self, *, cursor: str = "", limit: int = WIKI_LIST_LIMIT_MAX
    ) -> list[dict[str, Any]]:
        _validate_range(limit, low=1, high=WIKI_LIST_LIMIT_MAX, what="get_addable_knowledge_base_list 的 limit")
        payload = self._call("get_addable_knowledge_base_list", {"cursor": cursor, "limit": limit})
        value = payload.get("addable_knowledge_base_list")
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def list_items(
        self,
        knowledge_base_id: str,
        *,
        folder_id: str = "",
        limit: int = WIKI_LIST_LIMIT_MAX,
        cursor: str = "",
        sort_type: str = "UPDATE_TS_DESC_SORT_TYPE",
    ) -> dict[str, Any]:
        """浏览知识库内容（可传 folder_id 进入子文件夹）。

        官方 `get_knowledge_list` **未声明** `sort_type`；该字段沿用既有实现保留，
        服务端未报错即接受，但属未验证字段。
        """
        _validate_range(limit, low=1, high=WIKI_LIST_LIMIT_MAX, what="get_knowledge_list 的 limit")
        payload: dict[str, Any] = {
            "knowledge_base_id": knowledge_base_id,
            "cursor": cursor,
            "limit": limit,
            "sort_type": sort_type,
        }
        if folder_id:
            payload["folder_id"] = folder_id
        result = self._call("get_knowledge_list", payload)
        return {
            "items": self._items(result),
            "next_cursor": result.get("next_cursor", ""),
            "is_end": bool(result.get("is_end", False)),
            "current_path": result.get("current_path", []),
            "raw": result,
        }

    def search_items(self, knowledge_base_id: str, query: str, *, cursor: str = "") -> dict[str, Any]:
        """在知识库内搜索。响应字段为 `info_list`。"""
        result = self._call(
            "search_knowledge",
            {"knowledge_base_id": knowledge_base_id, "query": query, "cursor": cursor},
        )
        return {
            "items": self._items(result),
            "next_cursor": result.get("next_cursor", ""),
            "is_end": bool(result.get("is_end", False)),
            "raw": result,
        }

    def root_folder_id(self, knowledge_base_id: str) -> str:
        """取知识库的**真实**根目录 folder_id。

        ⚠️ 官方 api.md「文件夹说明」称「根目录的 folder_id 等于 knowledge_base_id」——
        **实测错误**。用 knowledge_base_id 当 folder_id 调 import_urls 会返回
        `code=222000 文件夹不存在`。真实值在 `get_knowledge_list` 的
        `current_path[0].folder_id`，与 knowledge_base_id 是两个不同的值。
        """
        result = self._call(
            "get_knowledge_list",
            {
                "knowledge_base_id": knowledge_base_id,
                "cursor": "",
                "limit": 1,
                "sort_type": "UPDATE_TS_DESC_SORT_TYPE",
            },
        )
        path = result.get("current_path")
        if isinstance(path, list) and path and isinstance(path[0], dict) and path[0].get("folder_id"):
            return str(path[0]["folder_id"])
        raise AdapterError(
            f"无法取得根目录 folder_id（get_knowledge_list.current_path 为空）: kb={knowledge_base_id}"
        )

    def check_repeated_names(
        self,
        *,
        knowledge_base_id: str,
        params: list[dict[str, Any]],
        folder_id: str = "",
    ) -> list[dict[str, Any]]:
        """上传前检查目标知识库/文件夹中是否已存在同名文件。

        `params` 形如 `[{"name": "report.pdf", "media_type": 1}, ...]`。
        **仅用于文件类型**（1/3/4/5/7/9/13/14/20/21），不用于网页(2/6)、笔记(11)。
        返回 `[{"name": ..., "is_repeated": bool}, ...]`。
        """
        cleaned: list[dict[str, Any]] = []
        for entry in params:
            name = str(entry.get("name", "")).strip()
            media_type = entry.get("media_type")
            if not name:
                raise ValueError("check_repeated_names 的每个 param 都需要非空 name")
            if not isinstance(media_type, int) or isinstance(media_type, bool):
                raise ValueError(f"check_repeated_names 的 media_type 必须是整数: {entry!r}")
            cleaned.append({"name": name, "media_type": media_type})
        if not cleaned:
            raise ValueError("params 不能为空")
        if len(cleaned) > CHECK_REPEATED_NAMES_LIMIT_MAX:
            raise ValueError(
                f"单次最多检查 {CHECK_REPEATED_NAMES_LIMIT_MAX} 个文件，当前 {len(cleaned)} 个"
            )
        payload: dict[str, Any] = {"params": cleaned, "knowledge_base_id": knowledge_base_id}
        if folder_id:
            payload["folder_id"] = folder_id
        result = self._call("check_repeated_names", payload)
        value = result.get("results")
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def fetch_media(self, media_id: str) -> dict[str, Any]:
        """取媒体访问信息。

        响应分支（实测）：
        - 普通媒体 → `{"media_type": N, "url_info": {"url": ..., "headers": {...}}}`
          取原文时**必须**带上 `url_info.headers` 中的头（含 `X-IMA-*`），否则签名校验失败。
        - 笔记类型 → `{"media_type": 11, "notebook_ext_info": {"notebook_id": ...}}`
          此时应把 `notebook_id` 当作 `note_id`，改走 `fetch_note_content`。
        - 不可访问 → 只有 `media_type`，无 `url_info`，需到 ima 客户端查看原文。
        """
        return self._call("get_media_info", {"media_id": media_id})

    @staticmethod
    def media_target(result: dict[str, Any]) -> tuple[str, Any]:
        """判断 `fetch_media` 结果该走哪条路。返回 `(kind, payload)`。

        - `("url", {"url":..., "headers":...})` — 直接下载
        - `("note", notebook_id)` — 改走笔记通道
        - `("client_only", None)` — 只能到 ima 客户端查看
        """
        media_type = result.get("media_type")
        url_info = result.get("url_info")
        if isinstance(url_info, dict) and url_info.get("url"):
            return "url", url_info
        if media_type == MEDIA_TYPE_NOTE:
            ext = result.get("notebook_ext_info")
            notebook_id = ext.get("notebook_id") if isinstance(ext, dict) else None
            if notebook_id:
                return "note", notebook_id
        return "client_only", None

    # ------------------------------------------------------------------ 读：笔记

    def fetch_note_content(
        self, note_id: str, *, target_content_format: int = CONTENT_FORMAT_PLAINTEXT
    ) -> str:
        """读取笔记正文。

        官方 `GetNoteContentReq` 把 `target_content_format` 标为**必填**：
        `0`=PLAINTEXT（推荐）、`1`=MARKDOWN（**不支持读**）、`2`=JSON。
        此处默认 0；传 1 会被服务端拒绝，属预期行为。
        """
        if target_content_format not in (
            CONTENT_FORMAT_PLAINTEXT,
            CONTENT_FORMAT_JSON,
        ):
            raise ValueError(
                "读笔记的 target_content_format 只支持 0(PLAINTEXT) 或 2(JSON)；"
                "1(MARKDOWN) 官方明确不支持读取"
            )
        result = self._call(
            "note_get_doc_content",
            {"note_id": note_id, "target_content_format": target_content_format},
        )
        for key in ("content", "note_content", "text"):
            value = result.get(key)
            if isinstance(value, str):
                return value
        raise AdapterError(f"笔记正文读取失败，返回中无 content 字段: note_id={note_id}")

    def list_notes(
        self,
        *,
        folder_id: str = "",
        cursor: str = "",
        limit: int = NOTE_LIST_LIMIT_MAX,
        sort_type: int = 0,
    ) -> dict[str, Any]:
        """列出笔记。返回 `note_book_list`（字段：note_id/title/summary/create_time/
        modify_time/cover_image/note_ext_info）。"""
        _validate_range(limit, low=1, high=NOTE_LIST_LIMIT_MAX, what="list_note 的 limit")
        payload: dict[str, Any] = {"cursor": cursor, "limit": limit, "sort_type": sort_type}
        if folder_id:
            payload["folder_id"] = folder_id
        result = self._call("note_list_note", payload)
        return {
            "items": self._items(result),
            "is_end": bool(result.get("is_end", False)),
            "raw": result,
        }

    def list_notebooks(self, *, cursor: str = "0", limit: int = NOTE_LIST_LIMIT_MAX) -> dict[str, Any]:
        """列出笔记本。**注意游标起始值是 `"0"`，不是空串**（与其它翻页接口不同）。"""
        _validate_range(limit, low=1, high=NOTE_LIST_LIMIT_MAX, what="list_notebook 的 limit")
        result = self._call("note_list_notebook", {"cursor": cursor, "limit": limit})
        value = result.get("note_folder_infos")
        return {
            "items": [item for item in value if isinstance(item, dict)] if isinstance(value, list) else [],
            "next_cursor": result.get("next_cursor", ""),
            "is_end": bool(result.get("is_end", False)),
            "next_version": result.get("next_version", ""),
            "raw": result,
        }

    def search_notes(
        self,
        *,
        title: str = "",
        content: str = "",
        search_type: int = 0,
        sort_type: int = 0,
        start: int = 0,
        end: int = SEARCH_NOTE_SPAN_MAX,
    ) -> dict[str, Any]:
        """搜索笔记。

        **实测：必须携带 `query_info`**，否则服务端返回
        `code=100001 ListNoteBook param error`（官方文档把 `query_info` 标为可选，与实现不符）。
        `search_type`：0=按标题，1=按正文。
        """
        if end - start > SEARCH_NOTE_SPAN_MAX:
            raise ValueError(f"search_note 的 end-start 不得超过 {SEARCH_NOTE_SPAN_MAX}，当前 {end - start}")
        if start < 0 or end <= start:
            raise ValueError(f"search_note 的翻页区间非法：start={start} end={end}")
        result = self._call(
            "note_search_note",
            {
                "search_type": search_type,
                "sort_type": sort_type,
                "query_info": {"title": title, "content": content},
                "start": start,
                "end": end,
            },
        )
        value = result.get("search_note_infos")
        return {
            "items": [item for item in value if isinstance(item, dict)] if isinstance(value, list) else [],
            "is_end": bool(result.get("is_end", False)),
            "total_hit_num": result.get("total_hit_num", 0),
            "raw": result,
        }

    @staticmethod
    def is_parsed(item: dict[str, Any]) -> bool:
        """写入是异步解析：不假设 add_knowledge 后立即可检索。"""
        return item.get("media_state") == MEDIA_STATE_PARSED

    @staticmethod
    def parse_progress(item: dict[str, Any]) -> int:
        value = item.get("parse_progress", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------ 写

    def import_urls(
        self, knowledge_base_id: str, urls: list[str], *, folder_id: str = ""
    ) -> dict[str, Any]:
        """批量导入网页/公众号文章。**实测可用。**

        官方 `folder_id` 为**必填**。⚠️ 官方文档称「根目录时填 knowledge_base_id」——
        实测错误，会返回 `222000 文件夹不存在`。此处留空时自动解析真实根目录
        （`root_folder_id()`，即 `get_knowledge_list` 的 `current_path[0].folder_id`）。
        """
        cleaned = [url.strip() for url in urls if url.strip()]
        if not cleaned:
            raise ValueError("urls 不能为空")
        if len(cleaned) > IMPORT_URLS_BATCH_LIMIT:
            raise ValueError(
                f"单次最多导入 {IMPORT_URLS_BATCH_LIMIT} 条，当前 {len(cleaned)} 条；请分批调用"
            )
        return self._call(
            "import_urls",
            {
                "knowledge_base_id": knowledge_base_id,
                "folder_id": folder_id or self.root_folder_id(knowledge_base_id),
                "urls": cleaned,
            },
        )

    def create_folder(
        self, *, knowledge_base_id: str, name: str, parent_folder_id: str = ""
    ) -> dict[str, Any]:
        """创建文件夹。**未文档化端点，2026-09-15 实测成功。**

        ⚠️ 返回的是 `{"media_id": "folder_xxx"}` —— 文件夹在 API 中也以 `media_id`
        形式标识，**不是** `folder_id`。后续 rename/move 都用这个 media_id。

        ⚠️ **父目录的线上字段名是 `folder_id`，不是 `parent_folder_id`**
        （2026-09-15 实测）：`parent_folder_id` 会被服务端**静默忽略**，导致子文件夹
        悄悄落到根目录。判据用「类型预言机」——给 `folder_id` 塞对象返回
        `code=1 cannot unmarshal object into Go value of type string`（字段存在），
        而 `parent_folder_id` 塞对象无任何报错（字段不存在）。
        本方法对外仍叫 `parent_folder_id`（语义清晰），内部映射为 `folder_id`。

        传入 `parent_folder_id` 即可建出**多级路径**；实测深度 3
        （库 → 自检A → 自检C）可正常创建并在 `current_path` 中反映。
        """
        if not name.strip():
            raise ValueError("文件夹名不能为空")
        if len(name) > 255:
            raise ValueError("文件夹名不得超过 255 字符")
        payload: dict[str, Any] = {"knowledge_base_id": knowledge_base_id, "name": name.strip()}
        if parent_folder_id:
            # 线上字段名是 folder_id（见 docstring 的实测判据）
            payload["folder_id"] = parent_folder_id
        return self._call("create_folder", payload)

    @staticmethod
    def is_folder(item: dict[str, Any]) -> bool:
        """判断 `get_knowledge_list` 的条目是不是文件夹。

        两个信号取或：`media_type == 99`（实测值，官方枚举表里没有）
        与 `media_id` 的 `folder_` 前缀（`create_folder` 实测返回形如 `folder_xxx`）。
        """
        media_id = str(item.get("media_id") or item.get("id") or "")
        return item.get("media_type") == MEDIA_TYPE_FOLDER or media_id.startswith("folder_")

    @staticmethod
    def folder_title(item: dict[str, Any]) -> str:
        """取文件夹/条目的显示名。实测字段是 `title`；`name` 作兜底。"""
        return str(item.get("title") or item.get("name") or "")

    def ensure_folder_path(
        self, *, knowledge_base_id: str, segments: list[str] | tuple[str, ...]
    ) -> str:
        """**幂等**地确保一条文件夹路径存在，返回最深层文件夹的 `media_id`。

        为什么要幂等：`create_folder` 每次都新建。若「每篇笔记都建一遍主题路径」，
        用不了几次目录里就会堆满同名文件夹。所以这里**先查后建**——
        逐级列举父目录下的文件夹，同名则复用，否则才创建。

        返回空串表示 `segments` 为空（即落在知识库根目录，不需要 folder_id）。
        """
        parts = [str(segment).strip() for segment in segments]
        if any(not part for part in parts):
            raise ValueError("路径段不能为空")
        if not parts:
            return ""

        parent_id = ""
        for depth, name in enumerate(parts, start=1):
            existing = self._find_child_folder(
                knowledge_base_id=knowledge_base_id, parent_folder_id=parent_id, name=name
            )
            if existing:
                parent_id = existing
                continue
            created = self.create_folder(
                knowledge_base_id=knowledge_base_id,
                name=name,
                parent_folder_id=parent_id,
            )
            media_id = str((created or {}).get("media_id") or "")
            if not media_id:
                raise AdapterError(
                    f"创建文件夹「{name}」（第 {depth} 级）未返回 media_id：{created!r}"
                )
            parent_id = media_id
        return parent_id

    def _find_child_folder(
        self, *, knowledge_base_id: str, parent_folder_id: str, name: str
    ) -> str:
        """在指定目录下按名找子文件夹。找到返回 `media_id`，否则空串。"""
        cursor = ""
        while True:
            page = self.list_items(
                knowledge_base_id, folder_id=parent_folder_id, cursor=cursor
            )
            for item in page.get("items") or []:
                if self.is_folder(item) and self.folder_title(item) == name:
                    return str(item.get("media_id") or item.get("id") or "")
            cursor = str(page.get("next_cursor") or "")
            if page.get("is_end") or not cursor:
                return ""

    def rename_knowledge(self, *, knowledge_base_id: str, media_id: str, name: str) -> dict[str, Any]:
        """原地重命名知识库条目（文件或文件夹）。**未文档化端点，2026-09-15 实测成功。**

        ⚠️ 这是官方 API 中**唯一**的原地「改」——IMA 没有通用的内容覆盖接口，
        正文层面的「改」仍然只能靠 append-only 表达。
        """
        if not knowledge_base_id.strip():
            raise ValueError("knowledge_base_id 不能为空")
        if not media_id.strip():
            raise ValueError("media_id 不能为空")
        if not name.strip():
            raise ValueError("新名称不能为空")
        if len(name) > 255:
            raise ValueError("新名称不得超过 255 字符")
        return self._call(
            "rename_knowledge",
            {"knowledge_base_id": knowledge_base_id, "media_id": media_id, "name": name.strip()},
        )

    def create_media(self, *, file_path: str | Path, knowledge_base_id: str) -> dict[str, Any]:
        """文件上传第一步：取 COS 上传凭证。上传前做扩展名 → MIME → 大小三重校验。"""
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"文件不存在: {path}")
        ext = path.suffix.lstrip(".").casefold()
        mime = EXT_TO_MIME.get(ext)
        if mime is None:
            # 依官方 skill 规则：找不到对照表时拒绝，不猜测
            raise ValueError(f"不支持的扩展名 .{ext}（官方 MIME 对照表中无此项，拒绝上传）")
        size = path.stat().st_size
        media_type = EXT_TO_MEDIA_TYPE.get(ext)
        if media_type is not None:
            limit = size_limit_for(media_type)
            if size > limit:
                raise ValueError(
                    f"文件超过官方大小上限：{path.name} 为 {size} 字节，"
                    f"media_type={media_type} 上限 {limit} 字节"
                )
        return self._call(
            "create_media",
            {
                "file_name": path.name,
                "file_size": size,
                "content_type": mime,
                "knowledge_base_id": knowledge_base_id,
                "file_ext": ext,
            },
        )

    def add_knowledge(
        self,
        *,
        knowledge_base_id: str,
        title: str,
        media_type: int = MEDIA_TYPE_MARKDOWN,
        media_id: str = "",
        folder_id: str = "",
        file_info: dict[str, Any] | None = None,
        web_info: dict[str, Any] | None = None,
        note_info: dict[str, Any] | None = None,
        session_info: dict[str, Any] | None = None,
        duplicate_name_strategy: str | None = None,
    ) -> dict[str, Any]:
        """把媒体挂进知识库。

        官方必填：`media_type` / `title` / `knowledge_base_id`。
        `media_id` 在**文件上传**时必填；`web_info` 在 `media_type=2` 时必填。
        `duplicate_name_strategy` **不在官方参数表内**，默认不发送（None）；
        仅在确认服务端接受时显式传入。
        """
        if not title.strip():
            raise ValueError("title 不能为空")
        if media_type == MEDIA_TYPE_WEBPAGE and not web_info:
            raise ValueError("media_type=2（网页）时必须提供 web_info（含 content_id=<url>）")
        payload: dict[str, Any] = {
            "knowledge_base_id": knowledge_base_id,
            "title": title,
            "media_type": media_type,
        }
        if media_id:
            payload["media_id"] = media_id
        if folder_id:
            payload["folder_id"] = folder_id
        if file_info:
            payload["file_info"] = file_info
        if web_info:
            payload["web_info"] = web_info
        if note_info:
            payload["note_info"] = note_info
        if session_info:
            payload["session_info"] = session_info
        if duplicate_name_strategy:
            payload["duplicate_name_strategy"] = duplicate_name_strategy
        return self._call("add_knowledge", payload)

    def create_note(
        self,
        content: str,
        *,
        title: str = "",
        folder_id: str = "",
        content_format: int = CONTENT_FORMAT_MARKDOWN,
    ) -> dict[str, Any]:
        """创建笔记。

        - `content_format` **固定为 1（MARKDOWN）**；`content` 必填；
          笔记标题由 Markdown 首个标题行推导。
        - `folder_id`：把笔记放进**已存在的**笔记本（官方 API 文档示例明确支持）。

        ⚠️ **本方法已移除 `folder_name` 参数**（2026-09-15 实测）：官方参数表里虽列了
        `folder_name`，但服务端**静默忽略**它——用「已有笔记本名」做撞名预言机
        （应报 `210030 notebook_NAME_EXIST`）**不报错**，用全新名字也**不会**建出笔记本；
        新建笔记后 `note_ext_info.folder_id` / `folder_name` 都是空串。
        **它不会自动创建笔记本，也不会按名匹配已有笔记本。**

        ⚠️ **建笔记本要走另一条端点**（2026-09-15 修正）：**`add_notebook`**
        （见本类 `add_notebook()`）。此前记的「无 create_notebook 端点」是**错的**——
        当时只探了 6 条「读型」候选、刻意回避「写型」，所以漏掉；
        `add_notebook` 不在官方技能包端点集里，属未文档化端点。
        """
        if not content.strip():
            raise ValueError("笔记内容不能为空")
        if content_format != CONTENT_FORMAT_MARKDOWN:
            raise ValueError("IMA 新建笔记目前仅支持 content_format=1（MARKDOWN）")
        payload: dict[str, Any] = {"content_format": content_format, "content": content}
        if title:
            payload["title"] = title
        if folder_id:
            payload["folder_id"] = folder_id
        return self._call("note_import_doc", payload)

    def add_notebook(self, *, folder_name: str) -> dict[str, Any]:
        """**新建笔记本**（未文档化端点，2026-09-15 实测通过）。

        - 必填字段名是 **`folder_name`**，**不是 `name`**
          （用 `name` 会报 `100001 文件名不能为空`，极具误导性）。
        - 返回 `{"folder_id": "folderxxx", "folder_name": "..."}`。
        - ⚠️ **笔记本是扁平的**：`parent_folder_id` 虽出现在 `list_notebook` 响应里，
          但**输入不认**（传了仍是空串）→ **无法建多级笔记本**。
          需要多级路径请用知识库侧 `create_folder` + `add_knowledge`。
        """
        cleaned = folder_name.strip()
        if not cleaned:
            raise ValueError("笔记本名不能为空")
        return self._call("note_add_notebook", {"folder_name": cleaned})

    def rename_notebook(self, *, folder_id: str, new_name: str) -> dict[str, Any]:
        """**给笔记本改名**（未文档化端点，2026-09-15 实测通过）。

        - 字段是 **`folder_id` + `new_folder_name`**；
          名字段**不叫** `name` / `folder_name` / `title`（15 个候选穷举出来的）。
        - ☠️ **不带 `new_folder_name` 调用会把笔记本名字清空**（实测：
          只传 `folder_id` 返 `code=0 success`，但名字变成空串）。
          **本方法因此强制要求 `new_name` 非空。**
        """
        if not folder_id.strip():
            raise ValueError("folder_id 不能为空")
        cleaned = new_name.strip()
        if not cleaned:
            raise ValueError(
                "new_name 不能为空：rename_notebook 不带新名会**把笔记本名字清空**（实测），"
                "故此处拒绝发送"
            )
        return self._call(
            "note_rename_notebook", {"folder_id": folder_id, "new_folder_name": cleaned}
        )

    def rename_note(self, *, note_id: str, title: str) -> dict[str, Any]:
        """**原地修改笔记标题**（未文档化端点，2026-09-15 实测通过）。

        字段为 `note_id` + `title`（protojson 同时接受 `note_id` 与 `noteId`）。
        与 `rename_knowledge`（知识库侧条目改名）配对：
        **笔记侧打 `IMSDEL` 待删标记用本方法，知识库侧用 `rename_knowledge`。**
        """
        if not note_id.strip():
            raise ValueError("note_id 不能为空")
        if not title.strip():
            raise ValueError("title 不能为空")
        return self._call("note_rename_note", {"note_id": note_id, "title": title})

    def mount_note_into_knowledge(
        self,
        *,
        knowledge_base_id: str,
        note_id: str,
        title: str,
        folder_id: str = "",
    ) -> dict[str, Any]:
        """**把一篇已有笔记挂进知识库的指定文件夹路径**（2026-09-15 实测通过）。

        这是回答「能否让每篇笔记都落到知识库某个路径下」的**关键手段**：
        走 `add_knowledge` + `media_type=11` + `note_info.content_id=<note_id>`。

        实测证据：挂载后回读该文件夹，条目 `media_type=11` 出现，且
        `current_path = [库名, 自检A, 笔记路径]`（深度 3）正确反映层级。

        ⚠️ 三点语义边界：
        1. **是「挂载/引用」而非「移动」**——笔记仍留在笔记系统里（可能仍未分类），
           知识库里多出一份指向它的条目。故 `move_knowledge` 空壳不影响本路径。
        2. 知识库里的**文件夹路径是多级的**（`create_folder` + `folder_id` 作父目录）；
           而**笔记本是扁平的**（见 `add_notebook`）。
        3. 挂载后的条目在知识库侧可 `rename_knowledge` 改名、按 `IMSDEL-` 打标。
        """
        if not knowledge_base_id.strip():
            raise ValueError("knowledge_base_id 不能为空")
        if not note_id.strip():
            raise ValueError("note_id 不能为空")
        return self.add_knowledge(
            knowledge_base_id=knowledge_base_id,
            title=title,
            media_type=MEDIA_TYPE_NOTE,
            folder_id=folder_id,
            note_info={"content_id": note_id},
        )

    def append_note(self, note_id: str, content: str, *, content_format: int = CONTENT_FORMAT_MARKDOWN) -> dict[str, Any]:
        """向已有笔记追加内容。**这是本系统表达「改」的唯一官方手段。**"""
        if not note_id.strip():
            raise ValueError("note_id 不能为空")
        if not content.strip():
            raise ValueError("追加内容不能为空")
        return self._call(
            "note_append_doc",
            {"note_id": note_id, "content_format": content_format, "content": content},
        )

    @staticmethod
    def build_event_append(object_title: str, event: str, detail: str, *, at: str) -> str:
        """构造追加内容。格式固定，便于本地物化视图解析。"""
        if not event.strip():
            raise ValueError("event 不能为空")
        lines = [f"\n## [{at}] {event}", ""]
        if object_title.strip():
            lines.append(f"- 对象：{object_title.strip()}")
        if detail.strip():
            lines.append(f"- 说明：{detail.strip()}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def build_tombstone(object_title: str, reason: str, *, at: str) -> str:
        """墓碑标记。IMA 侧不真删，只追加一条 [DELETED] 记录。"""
        return ImaAdapter.build_event_append(
            object_title, "[DELETED] 本地已归档", reason or "未说明原因", at=at
        )

    # ------------------------------------------------- 待删打标（改名方案）

    @staticmethod
    def new_deletion_batch(*, at: datetime | None = None) -> str:
        """生成一个「清理批次」令牌：`YYYYMMDD` + 4 位随机十六进制。

        随机后缀的作用：即使同一天分多批清理，批次之间也不会互相混淆。
        """
        moment = at or datetime.now()
        return f"{moment:%Y%m%d}{secrets.token_hex(2)}"

    @staticmethod
    def build_marked_title(title: str, *, batch: str) -> str:
        """把标题改写成带「待删」标记的形式：`IMSDEL-<batch>-<原标题>`。

        为什么用 `IMSDEL` 而不是 `[待删]`：

        - **可搜索**：IMA 客户端搜索对括号类符号的处理方式**未经实测**，因此只用
          字母/数字/连字符，规避符号可能带来的分词问题。
        - **不会误撞**：`IMSDEL` 是系统自造词，正常内容几乎不可能出现；
          再叠加 `<YYYYMMDD><4位随机>` 批次号，同一天的多次清理也可区分。
        - **可排序**：前缀定长（20 字符），客户端「按名称排序」时同一批的条目会聚在一起。

        幂等：若标题已带标记，会**替换**为新批次，不会重复叠加。
        """
        if not title.strip():
            raise ValueError("原标题不能为空")
        if not _DELETION_BATCH_RE.fullmatch(batch):
            raise ValueError(f"批次号格式非法（应为 YYYYMMDD+4位十六进制）：{batch!r}")
        return f"{DELETION_MARKER}-{batch}-{ImaAdapter.strip_mark(title)}"

    @staticmethod
    def is_marked_title(title: str) -> bool:
        """判断标题是否已带「待删」标记。"""
        return bool(_DELETION_MARK_RE.match(title.strip()))

    @staticmethod
    def strip_mark(title: str) -> str:
        """去掉「待删」标记，还原原标题。"""
        return _DELETION_MARK_RE.sub("", title.strip(), count=1)

    def mark_for_deletion(
        self, *, knowledge_base_id: str, media_id: str, title: str, batch: str
    ) -> dict[str, Any]:
        """给条目改名加「待删」前缀。**这是 API 侧唯一能做的打标动作。**

        完整工作流见报告 §4.2：本动作 → 客户端搜索/按名排序 → 框选 → 批量移动或删除。
        """
        return self.rename_knowledge(
            knowledge_base_id=knowledge_base_id,
            media_id=media_id,
            name=self.build_marked_title(title, batch=batch),
        )

    def unmark_for_deletion(
        self, *, knowledge_base_id: str, media_id: str, title: str
    ) -> dict[str, Any]:
        """撤销「待删」标记，把名字改回原标题。"""
        return self.rename_knowledge(
            knowledge_base_id=knowledge_base_id,
            media_id=media_id,
            name=self.strip_mark(title),
        )

    def move_knowledge(
        self,
        *,
        src_knowledge_base_id: str,
        dst_knowledge_base_id: str,
        media_ids: list[str] | None = None,
        dst_folder_id: str = "",
    ) -> dict[str, Any]:
        """把条目移到另一个知识库/文件夹。**未文档化端点，实测为「已声明但未实现」的空壳。**

        2026-09-15 两轮实测结论（均以真实响应为准）：

        1. **条目选择字段名已探明 = `media_ids`**，类型 `[]string`（元素必须是**裸字符串**）。
           证据用「类型预言机」取得，且先做了对照实验证明预言机有区分力：
           - 未知字段 `zzz_bogus_field_qqq` → **静默 code=0**（说明未知字段被忽略）
           - 已知字段 `dst_folder_id` 塞对象 → **code=1** 报错（说明已知字段错类型会报错）
           - `media_ids` 塞字符串 → **code=1** `cannot unmarshal string into Go value of
             type []json.RawMessage` → **证明字段真实存在**
           - `media_ids` 元素塞对象 → **code=1** `cannot unmarshal object into Go value of
             type string` → **证明元素类型是 string**
           - `knowledge_ids` / `doc_ids` / `ids` / `items` 塞字符串 → 全部静默 code=0 → **均不存在**
        2. 请求体字段已穷尽枚举：仅 `src_knowledge_base_id`、`dst_knowledge_base_id`、
           `dst_folder_id`、`media_ids` 四个（另试 12 个候选字段名全部不在 schema 中）。
        3. **即便如此，仍恒定返回 `code=0` 且 `move_results` 为空**，已排除以下原因：
           - ✅ 字段名错 → 已证为 `media_ids`
           - ✅ 元素形状错 → 已证为裸字符串
           - ✅ src == dst 导致空操作 → 已用**新建的第二个知识库**当 dst，仍为空
           - ✅ 物件类型受限 → 文件夹(media_type=99)、网页(media_type=2) 都试过
           - ✅ 缺必填字段 → 请求体已穷尽枚举，无遗漏

        → **结论：`move_knowledge` 高度疑似服务端「已声明但未实现」的空壳接口**
        （置信度：高）。旁证：腾讯官方 `Tencent/WeKnora` 的 IMA connector 也**完全不用**该端点。

        本方法在 `move_results` 为空时**显式抛错**，避免调用方误以为移动成功。
        **若要在知识库/文件夹之间整理条目，请走 ima 客户端**——客户端支持框选多条目后
        「移动到文件夹」，这条路是通的（API 不通，UI 通）。
        """
        selector_key = "media_ids"  # 2026-09-15 已探明：类型 []string，元素为裸字符串
        if not src_knowledge_base_id.strip() or not dst_knowledge_base_id.strip():
            raise ValueError("src/dst knowledge_base_id 不能为空")
        payload: dict[str, Any] = {
            "src_knowledge_base_id": src_knowledge_base_id,
            "dst_knowledge_base_id": dst_knowledge_base_id,
        }
        if media_ids:
            payload[selector_key] = list(media_ids)
        if dst_folder_id:
            payload["dst_folder_id"] = dst_folder_id
        result = self._call("move_knowledge", payload)
        moved = result.get("move_results")
        if not moved:
            raise AdapterError(
                "move_knowledge 返回空 move_results —— 该接口疑为服务端「已声明但未实现」的空壳"
                "（字段名 media_ids、元素形状、src≠dst 均已实测排除）。"
                "本次调用无任何效果。请改用 rename_knowledge，或到 ima 客户端手动移动"
                "（客户端支持框选多条目「移动到文件夹」）。"
            )
        return result

    def create_knowledge_base(
        self, *, name: str, kb_type: str = "KBT_MINE_KB", **_: Any
    ) -> dict[str, Any]:
        """创建知识库。**未文档化端点，2026-09-15 端到端验证成功。**

        ⚠️ 必填字段有 **两个**：`name` + `type`。
        早期只探明 `name`，是因为服务端校验**一次只报第一个**不合格字段——
        只传 `name` 会返回
        `code=51 invalid CreateKnowledgeBaseReq.Type: value must be in list
        [KBT_MINE_KB KBT_SHARED_KB KBT_SUBSCRIBED_CREATE_KB]`。
        补上 `type=KBT_MINE_KB` 后实测 `code=0`，返回 `{"id": "...", "name": "..."}`。

        ⚠️ **建好的知识库无法用 API 删除**（IMA 无删除能力），只能人工到客户端清理。
        因此本方法仅应在确实需要新建库时调用，不要用于测试。
        """
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("知识库名称不能为空")
        if len(cleaned) > 25:
            raise ValueError("知识库名称不得超过 25 字符（服务端正则上限）")
        if kb_type not in KB_TYPES:
            raise ValueError(f"kb_type 必须是 {sorted(KB_TYPES)} 之一，收到 {kb_type!r}")
        return self._call("create_knowledge_base", {"name": cleaned, "type": kb_type})

    # ---------------------------------------------------- 平台不具备的能力

    def delete_item(self, *_: Any, **__: Any) -> None:
        raise ImaCapabilityError(
            "IMA 官方接口不支持删除条目。2026-09-15 对 8 条 delete_*/remove_*/trash_* 候选路径"
            "（另有 7 条 update_*/modify_*/edit_* 候选）做了真实探测，**全部返回 HTTP 404**；"
            "官方文档、官方技能包与三处第三方独立实测结论一致。"
            "替代方案：① 到 ima 客户端手动删除；② 用 append-only 墓碑软删除"
            "（ImaAdapter.build_tombstone + 本地 InformationStore.tombstone）。"
            "**不要使用 cookie 逆向通道。**"
        )

    def update_item(self, *_: Any, **__: Any) -> None:
        raise ImaCapabilityError(
            "IMA 没有通用的「原地修改正文」接口。可选路径：① 正文变更用 "
            "ImaAdapter.append_note 追加带时间戳的记录（append-only）；"
            "② 仅「名称」可原地变更，用 ImaAdapter.rename_knowledge"
            "（未文档化端点，实测可用）。"
        )


@dataclass
class PulledItem:
    """拉取到的条目，`to_capture()` 供既有 CaptureAdapter 契约消费。"""

    media_id: str
    title: str
    knowledge_base_id: str = ""
    folder_id: str = ""
    introduction: str = ""
    media_state: int | None = None
    media_type: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, item: dict[str, Any], *, knowledge_base_id: str = "") -> "PulledItem":
        media_id = str(item.get("media_id", ""))
        if not media_id:
            raise AdapterError(f"IMA 条目缺少 media_id: {json.dumps(item, ensure_ascii=False)[:200]}")
        media_type = item.get("media_type")
        return cls(
            media_id=media_id,
            title=str(item.get("title", "")).strip() or media_id,
            knowledge_base_id=knowledge_base_id,
            folder_id=str(item.get("parent_folder_id", "")),
            introduction=str(item.get("introduction", "")),
            media_state=item.get("media_state"),
            media_type=media_type if isinstance(media_type, int) else None,
            raw=item,
        )

    def to_capture(self) -> dict[str, Any]:
        """转成 CaptureAdapter 契约字段（source/title/content）。"""
        return {
            "source": "ima",
            "title": self.title,
            "content": self.introduction or self.title,
            "source_ref": self.media_id,
            "source_container": self.knowledge_base_id,
        }
