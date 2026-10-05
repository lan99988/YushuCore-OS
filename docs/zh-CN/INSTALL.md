# 安装、升级与回滚

## 环境要求

- Python 3.11 或更高版本。
- Git 与克隆本仓库所需的网络连接。
- AI 宿主不是必需条件；可以独立使用 CLI。

## 从源码安装

```bash
git clone https://github.com/lan99988/Yushu2.0-OS.git
cd Yushu2.0-OS
python -m venv .venv
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

```bash
# macOS / Linux
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

可编辑安装会让部署命令能读取当前源码目录。只有需要 cron/interval 调度时才安装 `python -m pip install -e ".[automation]"`；本地运行完整验证时安装 `python -m pip install -e ".[dev,automation]"`。隔离演示和规则生命周期见[自动化指南](AUTOMATION.md)。

## 初始化并安全部署

默认 Core 数据目录是 `~/.yushuos`，应与源码目录分开。只有目标目录没有 `config.yaml` 时才复制模板；已存在的配置要保留并先检查。

```powershell
# Windows PowerShell
$coreHome = Join-Path $env:USERPROFILE '.yushuos'
New-Item -ItemType Directory -Force $coreHome | Out-Null
$config = Join-Path $coreHome 'config.yaml'
if (-not (Test-Path $config)) { Copy-Item '.\templates\core.yaml.template' $config }
yushuos --config-root $coreHome doctor
yushuos --config-root $coreHome deploy --source . --version 0.3.1 --preview
yushuos --config-root $coreHome verify --version 0.3.1
yushuos --config-root $coreHome activate --version 0.3.1
yushuos --config-root $coreHome doctor
yushuos --config-root $coreHome catalog
```

```bash
# macOS / Linux
core_home="$HOME/.yushuos"
mkdir -p "$core_home"
if [ ! -f "$core_home/config.yaml" ]; then cp templates/core.yaml.template "$core_home/config.yaml"; fi
yushuos --config-root "$core_home" doctor
yushuos --config-root "$core_home" deploy --source . --version 0.3.1 --preview
yushuos --config-root "$core_home" verify --version 0.3.1
yushuos --config-root "$core_home" activate --version 0.3.1
yushuos --config-root "$core_home" doctor
yushuos --config-root "$core_home" catalog
```

`deploy --preview` 只安装不可变候选版本，不切换活动版本；`verify` 检查文件哈希。二者成功后再激活。已部署版本不可覆盖；源码变化时使用新的版本标识。

## 安装宿主入口

宿主入口只是调用说明文件，不会安装插件、连接账号或授予写权限。先激活 Core 发布，再运行：

```powershell
$coreHome = Join-Path $env:USERPROFILE '.yushuos'
yushuos --config-root $coreHome install-host --host codex --host-config-root (Join-Path $env:USERPROFILE '.codex')
yushuos --config-root $coreHome install-host --host workbuddy --host-config-root (Join-Path $env:USERPROFILE '.workbuddy')
```

```bash
core_home="$HOME/.yushuos"
yushuos --config-root "$core_home" install-host --host codex --host-config-root "$HOME/.codex"
yushuos --config-root "$core_home" install-host --host workbuddy --host-config-root "$HOME/.workbuddy"
```

安装器不会覆盖非 YushuOS 管理的宿主文件。遇到冲突时先检查已有文件，再选择其他宿主配置目录或自行管理。`uninstall-host` 只移除未被修改的 YushuOS 托管入口。

## 升级与回滚

1. 更新源码仓库，并在同一虚拟环境中重新安装。
2. 用新的 Core 版本标识执行 `deploy --preview`。
3. 执行 `verify --version <新版本>`，检查 `doctor` 和 `catalog`。
4. 验证通过后激活新版本；上一个已验证版本会保留。
5. 若出现回归，运行 `rollback`，再检查 `doctor` 和 `catalog`。

Core 发布版本与插件版本相互独立。源码变化时不要复用旧版本标识。
