# Installation and upgrade

## Requirements

- Python 3.11 or newer.
- Git and network access to clone this repository.
- An AI host is optional; the CLI works on its own.

## Install from source

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

Editable installation keeps the checkout available to the Core deploy command. Install `python -m pip install -e ".[automation]"` only when cron/interval scheduling is needed. For local validation, install `python -m pip install -e ".[dev,automation]"`. See the [Automation guide](AUTOMATION.md) for the isolated demo and rule lifecycle.

## Initialize and deploy safely

The default Core home is `~/.yushuos`. Keep it separate from the source checkout. Copy the template only when there is no existing `config.yaml`; preserve and review existing configuration before changing it.

```powershell
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

`deploy --preview` installs an immutable candidate without switching the active release. `verify` checks its file hashes. Activate only after both succeed. A release ID is immutable: use a new ID for changed source files instead of overwriting a deployed version.

## Install a host bridge

A bridge is a small instruction file. It does not install plugins, connect accounts, or grant write permissions. Run this after activating a release:

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

The installer refuses to overwrite an unmanaged host file. Inspect a conflict and choose another host config root or manage that file yourself. `uninstall-host` removes only an unchanged managed bridge.

## Upgrade and rollback

1. Update the checkout and install it into the same virtual environment.
2. Deploy changed source under a new release ID with `deploy --preview`.
3. Verify the candidate and inspect `doctor` / `catalog`.
4. Activate only after verification; the previous verified release remains available.
5. If behavior regresses, run `rollback`, then verify `doctor` and `catalog` again.

Core release IDs and plugin versions are separate. Never reuse an ID for changed files.
