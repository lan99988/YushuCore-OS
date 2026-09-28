param(
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseRoot = if ($OutputRoot) { [System.IO.Path]::GetFullPath($OutputRoot) } else { Join-Path $projectRoot "release" }
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
$buildId = (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 6)
$buildRoot = Join-Path $releaseRoot "build-$buildId"
$distRoot = Join-Path $releaseRoot "dist-$buildId"
New-Item -ItemType Directory -Force -Path $buildRoot, $distRoot | Out-Null

Push-Location $projectRoot
try {
    uv run --with pyinstaller pyinstaller `
        --noconfirm --onedir --console --name Yushu `
        --distpath $distRoot --workpath $buildRoot --specpath $buildRoot `
        --add-data "$(Join-Path $projectRoot 'config/permission.yaml');config" `
        --add-data "$(Join-Path $projectRoot 'config/network.yaml');config" `
        --add-data "$(Join-Path $projectRoot 'config/integrations.yaml');config" `
        --add-data "$(Join-Path $projectRoot 'capability_plugins/manifests');capability_plugins/manifests" `
        --exclude-module integrations.llm_wiki `
        --exclude-module integrations.llm_wiki_client `
        --exclude-module integrations.obsidian `
        --exclude-module integrations.mcp `
        scripts/yushu_launcher.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$packageDir = Join-Path $distRoot "Yushu"
if (-not (Test-Path -LiteralPath (Join-Path $packageDir "Yushu.exe"))) {
    throw "Portable executable is missing"
}
Copy-Item -LiteralPath (Join-Path $projectRoot "docs/YUSHU_PORTABLE.md") -Destination (Join-Path $packageDir "README.md")
$zipPath = Join-Path $releaseRoot "Yushu-OS-Portable-$buildId.zip"
Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $zipPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
[pscustomobject]@{ Zip = $zipPath; Sha256 = $hash; Executable = (Join-Path $packageDir "Yushu.exe") } | ConvertTo-Json -Compress
