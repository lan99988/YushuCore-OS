# fix_feishu_hosts.ps1
# ============================================================
# 根治：lark-cli (Go) 访问 open.feishu.cn 时 TLS 握手超时
# 根因：DNS 轮询到特定 CDN IP 对 Go 超时；
#       Windows schannel(curl) 走的另一 IP 正常 (0.19s)
# 方案：固定 open.feishu.cn -> 202.168.162.164
#       （curl --resolve 验证对 /open-apis/... 实际 API 路径可达）
# 用法：右键本文件 -> 以管理员身份运行 PowerShell
#       或：powershell -ExecutionPolicy Bypass -File "D:\个人混合管理系统\fix_feishu_hosts.ps1"
# ============================================================
$hostsPath = "C:\Windows\System32\drivers\etc\hosts"
$ip        = "202.168.162.164"
$entry     = "$ip open.feishu.cn"

# 1. 备份
$stamp = Get-Date -Format "yyyyMMddHHmmss"
Copy-Item -Path $hostsPath -Destination "$hostsPath.bak.$stamp" -Force
Write-Host "[1/4] 已备份 hosts -> $hostsPath.bak.$stamp"

# 2. 去重追加
$raw = Get-Content -Path $hostsPath -Raw
if ($raw -match [regex]::Escape("open.feishu.cn")) {
    Write-Host "[2/4] hosts 已含 open.feishu.cn，跳过追加"
} else {
    Add-Content -Path $hostsPath -Value "`r`n$entry" -Encoding UTF8
    Write-Host "[2/4] 已追加: $entry"
}

# 3. 刷新 DNS 缓存
ipconfig /flushdns | Out-Null
Write-Host "[3/4] 已刷新 DNS 缓存"

# 4. 验证解析结果
try {
    $resolved = (Resolve-DnsName open.feishu.cn -ErrorAction Stop).IPAddress -join ", "
    Write-Host "[4/4] 解析结果: $resolved"
} catch {
    Write-Host "[4/4] 解析验证失败: $_"
}

Write-Host "`n✅ 根治完成。请在 AI 对话中回复「已修复」，让其立即重跑比赛录入命令。"
