"""Immutable local releases and guarded host integration."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any


_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9_-]*)*$")
_FORMAT = 1


def _root(value: str | Path) -> Path:
    path = Path(value).expanduser().absolute()
    if path.exists() and path.is_symlink():
        raise ValueError("目标根目录不能是链接")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _safe_version(value: str) -> str:
    if not isinstance(value, str) or not _VERSION.fullmatch(value) or value in {".", ".."}:
        raise ValueError("版本标识格式无效")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_map(root: Path, *, lock_name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("发布包不允许包含链接")
        if not path.is_file() or path.name == lock_name:
            continue
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in Path(relative).parts or path.suffix in {".pyc", ".pyo"}:
            continue
        result[relative] = _digest(path)
    return result


def _source_map(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        folder = root / name
        if any(item.is_symlink() for item in folder.rglob("*")):
            raise ValueError("发布源目录不能包含链接")
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            result[path.relative_to(root).as_posix()] = _digest(path)
    return result


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    if path.is_symlink() or not path.is_file():
        raise ValueError("YushuOS 状态文件必须是普通文件")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_launcher(root: Path) -> None:
    launcher = root / "bin" / "yushuos.py"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    source = "\n".join([
        "from pathlib import Path",
        "import hashlib, json, os, re, sys",
        "def fail(message):",
        "    print(json.dumps({'status': 'failed', 'message': message}, ensure_ascii=True))",
        "    raise SystemExit(1)",
        "root = Path(__file__).absolute().parents[1]",
        "state_path = root / 'active.json'",
        "if state_path.is_symlink() or not state_path.is_file(): fail('YushuOS 活动版本不可用')",
        "try:",
        "    state = json.loads(state_path.read_text(encoding='utf-8'))",
        "    version = state.get('active', '')",
        "    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,79}', version): fail('YushuOS 活动版本无效')",
        "    release = root / 'releases' / version",
        "    lock_path = release / 'release.lock.json'",
        "    if release.is_symlink() or lock_path.is_symlink() or not lock_path.is_file(): fail('YushuOS 活动版本不可用')",
        "    lock = json.loads(lock_path.read_text(encoding='utf-8'))",
        "    expected = lock.get('files')",
        "    if set(lock) != {'format', 'version', 'files'} or lock.get('format') != 1 or lock.get('version') != version or not isinstance(expected, dict): fail('YushuOS 发布清单无效')",
        "    actual = {}",
        "    for path in release.rglob('*'):",
        "        if path.is_symlink(): fail('YushuOS 发布包包含链接')",
        "        if path.is_file() and path != lock_path and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}:",
        "            actual[path.relative_to(release).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()",
        "    if actual != expected: fail('YushuOS 发布包校验失败')",
        "except (OSError, ValueError, TypeError, KeyError):",
        "    fail('YushuOS 活动版本或发布清单无效')",
        "sys.path.insert(0, str(release))",
        "os.environ['YUSHUOS_HOME'] = str(root)",
        "if '--config-root' not in sys.argv: sys.argv[1:1] = ['--config-root', str(root)]",
        "from yushuos.cli import main",
        "raise SystemExit(main())",
        "",
    ])
    if launcher.exists() and launcher.is_symlink():
        raise ValueError("YushuOS 启动器不能是链接")
    temporary = launcher.with_name(f".{launcher.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(source, encoding="utf-8")
        os.replace(temporary, launcher)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_release(config_root: str | Path, version: str | None = None) -> dict[str, Any]:
    root = _root(config_root)
    state = _read_json(root / "active.json", {})
    if not isinstance(state, dict):
        raise ValueError("active.json 格式无效")
    selected = _safe_version(version or state.get("active", ""))
    releases_root = root / "releases"
    if releases_root.is_symlink():
        return {"status": "failed", "version": selected, "verified": False, "reason": "release_directory_invalid"}
    release_root = releases_root / selected
    if release_root.is_symlink() or not release_root.is_dir():
        return {"status": "unavailable", "version": selected, "verified": False}
    lock_path = release_root / "release.lock.json"
    lock = _read_json(lock_path, None)
    if (not isinstance(lock, dict) or set(lock) != {"format", "version", "files"}
            or lock.get("format") != _FORMAT or lock.get("version") != selected or not isinstance(lock.get("files"), dict)):
        return {"status": "failed", "version": selected, "verified": False, "reason": "release_lock_invalid"}
    try:
        actual = _file_map(release_root, lock_name=lock_path.name)
    except (OSError, ValueError):
        return {"status": "failed", "version": selected, "verified": False, "reason": "release_files_invalid"}
    expected = lock["files"]
    verified = actual == expected and all(isinstance(k, str) and isinstance(v, str) for k, v in expected.items())
    return {"status": "succeeded" if verified else "failed", "version": selected, "verified": verified,
            "file_count": len(actual), "reason": None if verified else "release_hash_mismatch"}


def _activate_release(root: Path, version: str) -> dict[str, Any]:
    verification = verify_release(root, version)
    if not verification["verified"]:
        raise ValueError("必须先部署并验证候选版本")
    state = _read_json(root / "active.json", {"format": _FORMAT, "active": "", "previous": []})
    if not isinstance(state, dict) or not isinstance(state.get("previous", []), list):
        raise ValueError("部署状态格式无效")
    previous = [item for item in state.get("previous", []) if isinstance(item, str) and item != version]
    active = state.get("active", "")
    if active and active != version:
        previous.insert(0, _safe_version(active))
    _atomic_json(root / "active.json", {"format": _FORMAT, "active": version, "previous": previous[:10]})
    _write_launcher(root)
    return {"status": "succeeded", "version": version, "verified": True,
            "active": True, "previous_active": active or None}


def activate_release(config_root: str | Path, version: str) -> dict[str, Any]:
    root = _root(config_root)
    return _activate_release(root, _safe_version(version))


def deploy(source: str | Path, config_root: str | Path, version: str, *, activate: bool = True) -> dict[str, Any]:
    version = _safe_version(version)
    source_root = Path(source).expanduser().absolute()
    if source_root.is_symlink() or not source_root.is_dir():
        raise ValueError("发布源必须是普通目录")
    required = ("yushuos", "yushuos_sdk", "templates")
    for name in required:
        folder = source_root / name
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError(f"发布源缺少目录：{name}")
    root = _root(config_root)
    releases = root / "releases"
    if releases.exists() and releases.is_symlink():
        raise ValueError("releases 目录不能是链接")
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / version
    if release.exists():
        result = verify_release(root, version)
        if not result["verified"]:
            raise ValueError("该版本已存在且校验失败；不可覆盖不可变发布")
        lock = _read_json(release / "release.lock.json", {})
        if lock.get("files") != _source_map(source_root, required):
            raise ValueError("该版本已存在但源代码已改变；请递增版本后发布")
        if activate:
            return {**_activate_release(root, version), "already_present": True}
        return {"status": "succeeded", "version": version, "verified": True,
                "active": False, "already_present": True}

    staging = releases / f".stage-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        for name in required:
            src = source_root / name
            if any(item.is_symlink() for item in src.rglob("*")):
                raise ValueError("发布源目录不能包含链接")
            shutil.copytree(src, staging / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        files = _file_map(staging, lock_name="release.lock.json")
        lock = {"format": _FORMAT, "version": version, "files": files}
        (staging / "release.lock.json").write_text(json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if _file_map(staging, lock_name="release.lock.json") != files:
            raise ValueError("暂存发布校验失败")
        staging.rename(release)
        verification = verify_release(root, version)
        if not verification["verified"]:
            raise ValueError("发布包写入后校验失败")
        activated = _activate_release(root, version) if activate else {
            "status": "succeeded", "version": version, "verified": True, "active": False,
        }
        return {**activated, "file_count": len(files), "already_present": False}
    except Exception:
        if staging.exists() and staging.parent == releases and staging.name.startswith(".stage-"):
            shutil.rmtree(staging)
        raise


def rollback(config_root: str | Path) -> dict[str, Any]:
    root = _root(config_root)
    state_path = root / "active.json"
    state = _read_json(state_path, None)
    if not isinstance(state, dict) or not isinstance(state.get("previous"), list) or not state.get("active"):
        return {"status": "unavailable", "message": "没有可回滚的已部署版本"}
    active = _safe_version(state["active"])
    previous = [_safe_version(item) for item in state["previous"] if isinstance(item, str)]
    if not previous:
        return {"status": "unavailable", "message": "没有可回滚的已部署版本"}
    target = previous[0]
    verification = verify_release(root, target)
    if not verification["verified"]:
        return {"status": "failed", "active": active, "version": target, "message": "候选回滚版本未通过哈希校验"}
    _atomic_json(state_path, {"format": _FORMAT, "active": target, "previous": [active, *previous[1:]][:10]})
    return {"status": "succeeded", "previous_active": active, "active": target, "verified": True}


def _host_content(host: str, config_root: Path, python_executable: str) -> str:
    launcher = (config_root / "bin" / "yushuos.py").as_posix()
    command = f'"{python_executable}" "{launcher}" --config-root "{config_root.as_posix()}"'
    if host == "codex":
        lines = [
            "---", "name: yushuos-core",
            "description: Route registered personal-system capabilities through the YushuOS lightweight Core.", "---", "",
            "# YushuOS Core", "",
            "For registered personal-system requests, use the catalog to identify the capability and pass a contract-compliant request through the shared Core CLI. The host owns natural-language understanding; Core resolves the versioned provider and enforces schemas, explicit write gates, receipts, and workflow state. Domain logic stays in the selected plugin.", "",
            "Keep legacy command prefixes on their existing compatibility route until a specific migration mapping has been registered. Do not infer a new App capability for an old prefix just because the names look similar.", "",
            f'Use this command prefix: `{command}`. Start with `doctor` and `catalog`. Use `parse --text "#prefix ..."` to resolve an explicit plugin prefix; ordinary natural-language intent remains host-owned. Add `--project-file <path>` when using project scope. For writes, require explicit user intent, preview first, and execute only when host policy authorizes it. Never retry an unknown result; inspect `status` or `resume` using the original request ID.', "",
            'Use `catalog --details` to inspect execution modes, scopes, and schemas. Preview automation with `automation preview --rule <id>`. Granting or enabling a rule requires explicit user authorization; a host_pending result is not permission to grant. Take over the same run only with explicit execution approval using `automation run --rule <id> --run-id <run-id> --host-mode execute`. Unknown results require readback and an explicit `history resolve` before resume; never generate a new request ID to bypass uncertainty.', '',
        ]
    else:
        lines = [
            "# YushuOS Core Rule", "",
            "对已登记的个人系统请求，宿主先根据 catalog 识别能力，再把符合契约的请求交给 YushuOS Core。宿主负责自然语言理解；Core 负责解析显式前缀、选择已配置版本、校验 Schema、写入门禁、共享收据和流程状态。领域规则和业务数据由插件拥有。", "",
            "未完成逐项迁移的旧命令前缀继续走原兼容入口。除非有明确登记的迁移映射，不得仅因名称相似就把旧命令猜测映射到新 App 能力。", "",
            f'CLI 命令前缀：`{command}`。先运行 `doctor` 和 `catalog`；显式前缀可用 `parse --text "#prefix ..."`。项目请求需加 `--project-file <path>`。普通对话仍由宿主处理。任何写入都先预览，只在用户明确提出写入且宿主策略授权后执行。未知结果必须用原请求 ID 查询，不得盲目重试。', "",
            '用 `catalog --details` 检查 execution_mode、Schema 和资源范围。自动化先执行 `automation preview --rule <id>`；grant/enable 必须得到用户明确授权，host_pending 不构成授权。宿主仅在获准执行后用 `automation run --rule <id> --run-id <run-id> --host-mode execute` 接管原运行。unknown 必须先读回核验，再显式 history resolve 和接续，不得用新请求 ID 绕开未决结果。', '',
        ]
    return "\n".join(lines)


def _ensure_no_links(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("宿主目标路径越出配置根目录") from exc
    current = root
    if current.exists() and current.is_symlink():
        raise ValueError("宿主配置根目录不能是链接")
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("宿主目标路径不能经过链接")


def install_host(config_root: str | Path, host_config_root: str | Path, *, host: str) -> dict[str, Any]:
    if host not in {"codex", "workbuddy"}:
        raise ValueError("宿主必须是 codex 或 workbuddy")
    root = _root(config_root)
    from .config import load_config
    runtime_config = load_config(root)
    if not runtime_config["hosts"][host]:
        raise ValueError("本体配置已停用该宿主接入")
    verification = verify_release(root)
    if not verification["verified"]:
        raise ValueError("必须先部署并验证活动版本")
    state = _read_json(root / "host-installs.json", {"format": _FORMAT, "hosts": {}})
    if not isinstance(state, dict) or not isinstance(state.get("hosts"), dict):
        raise ValueError("宿主安装记录格式无效")
    host_root = Path(host_config_root).expanduser().absolute()
    if host_root.exists() and host_root.is_symlink():
        raise ValueError("宿主配置目录不能是链接")
    target = host_root / "skills" / "yushuos-core" / "SKILL.md" if host == "codex" else host_root / "rules" / "yushuos-core.md"
    _ensure_no_links(host_root, target)
    previous = state["hosts"].get(host)
    old_content = target.read_bytes() if target.exists() else None
    if target.exists():
        if not isinstance(previous, dict) or previous.get("target") != str(target):
            raise ValueError("目标文件已存在且并非本安装器管理；为保护原文件，已停止安装")
        if _digest(target) != previous.get("installed_sha256"):
            raise ValueError("受管宿主文件已被修改；保留现状并停止覆盖")
    python_executable = runtime_config.get("runtime", {}).get("python_executable") or sys.executable
    content = _host_content(host, root, python_executable).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_bytes(content)
        os.replace(temp, target)
        state["hosts"][host] = {
            "target": str(target), "installed_sha256": hashlib.sha256(content).hexdigest(),
            "release": verification["version"], "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(root / "host-installs.json", state)
    except Exception:
        if target.exists() and _digest(target) == hashlib.sha256(content).hexdigest():
            if old_content is None:
                target.unlink()
            else:
                target.write_bytes(old_content)
        raise
    finally:
        if temp.exists():
            temp.unlink()
    return {"status": "succeeded", "host": host, "installed": True, "release": verification["version"]}


def uninstall_host(config_root: str | Path, host_config_root: str | Path, *, host: str) -> dict[str, Any]:
    """Remove only the exact, unmodified host entry installed by YushuOS."""
    if host not in {"codex", "workbuddy"}:
        raise ValueError("宿主必须是 codex 或 workbuddy")
    root = _root(config_root)
    state = _read_json(root / "host-installs.json", {"format": _FORMAT, "hosts": {}})
    if not isinstance(state, dict) or not isinstance(state.get("hosts"), dict):
        raise ValueError("宿主安装记录格式无效")
    host_root = Path(host_config_root).expanduser().absolute()
    target = host_root / "skills" / "yushuos-core" / "SKILL.md" if host == "codex" else host_root / "rules" / "yushuos-core.md"
    _ensure_no_links(host_root, target)
    record = state["hosts"].get(host)
    if not isinstance(record, dict):
        return {"status": "unavailable", "host": host, "removed": False}
    if record.get("target") != str(target):
        raise ValueError("安装记录与指定宿主目标不匹配")
    if target.exists():
        if target.is_symlink() or not target.is_file() or _digest(target) != record.get("installed_sha256"):
            raise ValueError("宿主入口已被修改；为保护用户内容，拒绝删除")
        target.unlink()
    del state["hosts"][host]
    _atomic_json(root / "host-installs.json", state)
    return {"status": "succeeded", "host": host, "removed": True}


def lock_plugin(plugin_root: str | Path) -> dict[str, Any]:
    from .manifest import load_manifest

    root = Path(plugin_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("插件目录必须是普通目录")
    manifest = next((root / name for name in ("plugin.yaml", "plugin.yml") if (root / name).is_file()), None)
    if manifest is None:
        raise ValueError("插件目录缺少 plugin.yaml")
    spec = load_manifest(manifest, verify_lock=False)
    files = _file_map(root, lock_name="plugin.lock.json")
    lock = {"format": _FORMAT, "plugin_id": spec.plugin_id, "version": spec.version, "files": files}
    lock_path = root / "plugin.lock.json"
    if lock_path.exists() and lock_path.is_symlink():
        raise ValueError("插件锁定清单不能是链接")
    _atomic_json(lock_path, lock)
    verified = load_manifest(manifest).package_hash_verified
    return {"status": "succeeded" if verified else "failed", "plugin_id": spec.plugin_id,
            "version": spec.version, "file_count": len(files), "verified": verified}


def install_plugin(plugin_source: str | Path, config_root: str | Path) -> dict[str, Any]:
    """Install one hash-verified plugin version without selecting or enabling it."""
    from .manifest import load_manifest

    source = Path(plugin_source).expanduser().absolute()
    if source.is_symlink() or not source.is_dir() or any(item.is_symlink() for item in source.rglob("*")):
        raise ValueError("插件源必须是无链接的普通目录")
    manifest = next((source / name for name in ("plugin.yaml", "plugin.yml") if (source / name).is_file()), None)
    if manifest is None:
        raise ValueError("插件源缺少 plugin.yaml")
    spec = load_manifest(manifest)
    if not spec.package_hash_verified:
        raise ValueError("插件源必须提供有效的 plugin.lock.json")

    root = _root(config_root)
    plugins_root = root / "plugins"
    if plugins_root.exists() and (plugins_root.is_symlink() or not plugins_root.is_dir()):
        raise ValueError("插件安装根目录必须是普通目录")
    plugins_root.mkdir(parents=True, exist_ok=True)
    plugin_root = plugins_root / spec.plugin_id
    if plugin_root.exists() and (plugin_root.is_symlink() or not plugin_root.is_dir()):
        raise ValueError("插件目标目录无效")
    plugin_root.mkdir(parents=True, exist_ok=True)
    target = plugin_root / spec.version
    if target.exists():
        installed = load_manifest(target / "plugin.yaml")
        if installed.plugin_id != spec.plugin_id or installed.version != spec.version or not installed.package_hash_verified:
            raise ValueError("同 ID/版本已存在不同或损坏的插件；不可覆盖")
        if _file_map(source, lock_name="plugin.lock.json") != _file_map(target, lock_name="plugin.lock.json"):
            raise ValueError("同 ID/版本源内容不同；插件版本不可变，请递增版本号")
        return {"status": "succeeded", "plugin_id": spec.plugin_id, "version": spec.version,
                "installed": True, "selected": False, "already_present": True}

    staging = plugin_root / f".stage-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        installed = load_manifest(staging / "plugin.yaml")
        if (installed.plugin_id != spec.plugin_id or installed.version != spec.version
                or not installed.package_hash_verified):
            raise ValueError("插件暂存包校验失败")
        staging.rename(target)
    except Exception:
        if staging.exists() and staging.parent == plugin_root and staging.name.startswith(".stage-"):
            shutil.rmtree(staging)
        raise
    return {"status": "succeeded", "plugin_id": spec.plugin_id, "version": spec.version,
            "installed": True, "selected": False, "already_present": False}


def sync_app_plugin(config_root: str | Path, app_root: str | Path, *, app: str) -> dict[str, Any]:
    """Create an immutable descriptor adapter, retaining legacy IMA/Feishu support."""
    if not isinstance(app,str) or not _CAPABILITY_ID.fullmatch(app):
        raise ValueError('App 标识无效')
    import yaml
    from .manifest import load_manifest

    root = _root(config_root)
    app_install = Path(app_root).expanduser().absolute()
    if app_install.is_symlink() or not app_install.is_dir():
        raise ValueError("App 安装目录必须是普通目录")
    pointer = app_install / app / "active.json"
    if pointer.is_symlink() or not pointer.is_file():
        raise ValueError("App 缺少活动版本指针")
    binding = _read_json(pointer, None)
    if not isinstance(binding, dict) or binding.get("app") != app:
        raise ValueError("App 活动指针格式不匹配")
    version = _safe_version(binding.get("version", ""))
    release = Path(binding.get("release", "")).expanduser()
    if not release.is_absolute() or release.is_symlink() or not release.is_dir():
        raise ValueError("App 发布目录不可用")
    for key in ("config_file", "ledger_path", "python_executable"):
        value = binding.get(key)
        if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
            raise ValueError(f"App 活动指针缺少绝对路径 {key}")
        path = Path(value).expanduser()
        if any(item.is_symlink() or getattr(item, "is_junction", lambda: False)() for item in (path, *path.parents)):
            raise ValueError("App 活动指针包含链接路径")
    if not Path(binding["config_file"]).is_file() or not Path(binding["python_executable"]).is_file() or not Path(binding["ledger_path"]).is_file():
        raise ValueError("App 配置、稳定 Python 或共享台账不存在")
    release_manifest = _read_json(release / "manifest.json", None)
    if not isinstance(release_manifest, dict) or release_manifest.get("app") != app or release_manifest.get("version") != version:
        raise ValueError("App 发布清单版本不匹配")
    if _file_map(release, lock_name="manifest.json") != release_manifest.get("files"):
        raise ValueError("App 发布包完整性校验失败")
    descriptor_file=release/'app-descriptor.json'
    descriptor=None
    if descriptor_file.exists():
        from .app_descriptor import load_app_descriptor
        descriptor=load_app_descriptor(descriptor_file)
        if descriptor['app']!=app or descriptor['version']!=version:
            raise ValueError('App Descriptor 与活动版本不匹配')
        declared_capabilities=[{'id':c['id'],'implemented':True} for c in descriptor['capabilities']]
    else:
        if app not in {'ima','feishu'}:
            raise ValueError('通用 App 必须提供 app-descriptor.json')
        capability_file = release / "apps" / app / "capabilities.json"
        if capability_file.is_symlink() or not capability_file.is_file():
            raise ValueError("App 发布包缺少能力目录")
        declared_capabilities = json.loads(capability_file.read_text(encoding="utf-8-sig"))
    if not isinstance(declared_capabilities, list):
        raise ValueError("App 能力目录格式无效")
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
           or type(item.get("implemented")) is not bool for item in declared_capabilities):
        raise ValueError("App 静态能力目录字段无效")

    # The App's local catalog is read-only and reflects its real verification,
    # authorization, and disabled state. Never advertise an implemented API as
    # available merely because it appears in the static capability catalog.
    catalog_command = [binding["python_executable"], str(release / "app_plugins" / "__main__.py"),
                       "--app", app, "--config-file", binding["config_file"],
                       "--ledger-path", binding["ledger_path"], "--version", version, "catalog"]
    env_names = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA")
    catalog_env = {name: os.environ[name] for name in env_names if name in os.environ}
    catalog_env["PYTHONUTF8"] = "1"
    catalog_env["PYTHONPATH"] = str(release)
    try:
        catalog_process = subprocess.run(catalog_command, capture_output=True, text=True, encoding="utf-8",
                                         timeout=30, cwd=str(release), env=catalog_env)
        app_catalog = json.loads(catalog_process.stdout, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError("App 本地能力目录读取失败") from exc
    if (catalog_process.returncode != 0 or not isinstance(app_catalog, dict) or app_catalog.get("app") != app
            or not isinstance(app_catalog.get("capabilities"), list)):
        raise ValueError("App 本地能力目录格式无效")
    capabilities = app_catalog["capabilities"]
    declared_ids = {item.get("id") for item in declared_capabilities if isinstance(item, dict)}
    catalog_ids = {item.get("id") for item in capabilities if isinstance(item, dict)}
    if (len(catalog_ids) != len(capabilities) or catalog_ids != declared_ids
            or any(not isinstance(item, dict)
                   or any(type(item.get(flag)) is not bool for flag in ("implemented", "verified", "authorized", "enabled"))
                   for item in capabilities)):
        raise ValueError("App 本地能力状态与静态目录不匹配")

    write_intents = {
        "knowledge.create": ["capture"], "knowledge.append": ["update"],
        "task.create": ["capture"], "task.update": ["update"], "task.complete": ["update"],
        "calendar.create": ["capture", "schedule"], "calendar.update": ["update", "schedule"],
        "feishu.tasklist.create": ["capture"],
    }
    generated = []
    skipped = 0
    descriptors={c['id']:c for c in descriptor['capabilities']} if descriptor else {}
    for item in capabilities:
        capability = item.get("id") if isinstance(item, dict) else None
        if not isinstance(capability, str) or not _CAPABILITY_ID.fullmatch(capability):
            skipped += 1
            continue
        implemented = item.get("implemented") is True
        if descriptor:
            definition=descriptors[capability]
            generated.append({'name':capability,'description':definition['description'],
                'effect':definition['effect'],'inputs':definition['input_schema'],'outputs':definition['output_schema'],
                'execution_mode':definition['execution_mode'],'dependencies':[],
                'permissions':definition['auth']['scopes'] if definition['auth']['required'] else [], 'resource_scopes':definition['resource_bindings'],
                'intents':[definition['intent']],'implemented':implemented,'verified':item['verified'],
                'authorized':not definition['auth']['required'] or item['authorized'],'enabled':item['enabled']})
            continue
        intents = write_intents.get(capability)
        if intents is None and capability in {"ima.kb.create_media", "ima.kb.associate", "ima.kb.import_urls", "ima.note.images.append", "ima.video.import"}:
            intents = ["capture"]
        if intents is None:
            intents = ["query"]
        effect = "external_write" if capability in write_intents or capability in {
            "ima.kb.create_media", "ima.kb.associate", "ima.kb.import_urls", "ima.note.images.append", "ima.video.import"
        } else "read_only"
        generated.append({
            "name": capability, "effect": effect,
            "inputs": {"type": "object"}, "outputs": {"type": "any"},
            "dependencies": [], "permissions": [capability] if effect == "external_write" else [],
            "resource_scopes": {},
            "intents": intents, "implemented": implemented, "verified": item.get("verified") is True,
            "authorized": item.get("authorized") is True, "enabled": item.get("enabled") is True,
        })
    if not generated:
        raise ValueError("App 没有可安全登记的能力名称")

    plugin_id = f"app-{app}"
    plugin_root = root / "plugins" / plugin_id
    if plugin_root.exists() and plugin_root.is_symlink():
        raise ValueError("App 插件目录不能是链接")
    plugin_root.mkdir(parents=True, exist_ok=True)
    target = plugin_root / version
    if target.exists():
        spec = load_manifest(target / "plugin.yaml")
        if spec.plugin_id != plugin_id or spec.version != version or not spec.package_hash_verified:
            raise ValueError("同版本 YushuOS App 插件已存在且不匹配；不可覆盖")
        result = {"status": "succeeded", "app": app, "plugin_id": plugin_id, "version": version,
                  "capability_count": len(spec.capabilities), "already_present": True}
    else:
        staging = plugin_root / f".stage-{uuid.uuid4().hex}"
        template = Path(__file__).resolve().parents[1] / "templates" / "app-plugin-template"
        if template.is_symlink() or not template.is_dir():
            raise ValueError("App 插件模板不存在")
        try:
            shutil.copytree(template, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            manifest = {
                "id": plugin_id, "name": f"App Adapter: {app}", "version": version,
                "contract_version": 3 if descriptor else 2, "type": "app",
                "description": f"独立 {app} App 插件的 YushuOS 受控适配入口。",
                "enabled": True, "dependencies": [], "optional_dependencies": [], "permissions": [],
                "data_path": "data", "supported_runtimes": ["python>=3.11"],
                "configuration": {"type": "object", "additionalProperties": False},
                "error_policy": "fail_closed", "audit_policy": "metadata_only",
                "runner": {"command": ["{python}", "{plugin_root}/run.py"],
                            "timeout_seconds": 90, "protocol": "json-stdio-v2" if descriptor else "json-stdio-v1"},
                "capabilities": generated, "routes": [], "skill_names": [plugin_id],
            }
            (staging / "plugin.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
            lock_plugin(staging)
            staging.rename(target)
            result = {"status": "succeeded", "app": app, "plugin_id": plugin_id, "version": version,
                      "capability_count": len(generated), "implemented_count": sum(item["implemented"] for item in generated),
                      "skipped_nonportable_ids": skipped, "already_present": False}
        except Exception:
            if staging.exists() and staging.parent == plugin_root and staging.name.startswith(".stage-"):
                shutil.rmtree(staging)
            raise

    bindings_dir = root / "bindings.d"
    if bindings_dir.exists() and (bindings_dir.is_symlink() or not bindings_dir.is_dir()):
        raise ValueError("bindings.d 必须是普通目录")
    bindings_dir.mkdir(parents=True, exist_ok=True)
    binding_file = bindings_dir / f"{plugin_id}.yaml"
    if binding_file.is_symlink():
        raise ValueError("App 绑定文件不能是链接")
    if binding_file.exists():
        if not binding_file.is_file():
            raise ValueError("App 绑定文件必须是普通文件")
        current = yaml.safe_load(binding_file.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(current, dict):
            raise ValueError("App 绑定文件根节点必须是对象")
    else:
        current = {}
    if set(current) - {"schema_version", "plugins", "bindings"}:
        raise ValueError("既有 App 绑定文件包含不受管理字段；保留原文件")
    current.setdefault("schema_version", 1)
    if current["schema_version"] != 1:
        raise ValueError("既有 App 绑定文件版本不支持")
    plugins = current.setdefault("plugins", {})
    app_bindings = current.setdefault("bindings", {})
    if not isinstance(plugins, dict) or set(plugins) - {"versions"} or not isinstance(app_bindings, dict) or set(app_bindings) - {"apps"}:
        raise ValueError("既有 App 绑定文件包含不受管理字段；保留原文件")
    versions = plugins.setdefault("versions", {})
    apps = app_bindings.setdefault("apps", {})
    if not isinstance(versions, dict) or not isinstance(apps, dict):
        raise ValueError("既有 App 绑定文件字段格式无效")
    versions[plugin_id] = version
    apps[plugin_id] = {"active_pointer": str(pointer)}
    binding_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = binding_file.with_name(f".{binding_file.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(yaml.safe_dump(current, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.replace(temporary, binding_file)
    finally:
        if temporary.exists():
            temporary.unlink()
    from .config import load_config
    loaded_config = load_config(root)
    configured_ledger = loaded_config["state"]["ledger_path"]
    if configured_ledger:
        configured_path = Path(configured_ledger).expanduser()
        if not configured_path.is_absolute():
            configured_path = root / configured_path
        shared_ledger_configured = configured_path.resolve() == Path(binding["ledger_path"]).expanduser().resolve()
    else:
        shared_ledger_configured = False
    return {**result, "binding_written": True, "shared_ledger_configured": shared_ledger_configured,
            **({'descriptor_version':1} if descriptor else {})}
