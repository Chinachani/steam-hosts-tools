<#
.SYNOPSIS
    Steam Hosts 一键防污染优选与更新脚本 (PowerShell 版)
.DESCRIPTION
    1. 采用 DoH (DNS-over-HTTPS) 加密防污染解析，杜绝 DNS 投毒
    2. 全域名 TCP 443 端口并发测活与 RTT 延迟优选
    3. 自动清洗历史记录、自动备份、自动刷新 Windows DNS 缓存
.PARAMETER DryRun
    仅预览推荐节点，不修改 hosts
.PARAMETER Clean
    清理并移除所有现存 Steam 记录
#>

param(
    [string]$HostsPath = "$env:SystemRoot\System32\drivers\etc\hosts",
    [string]$BackupDir = "$PSScriptRoot\hosts_backup",
    [switch]$DryRun,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Success($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-WarnMsg($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-ErrMsg($msg) { Write-Host "[ERR]  $msg" -ForegroundColor Red }

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $DryRun -and -not $isAdmin) {
    Write-ErrMsg "权限不足！修改 hosts 文件需要以管理员身份运行。"
    Write-Host "提示：请右键以「管理员身份运行」打开 PowerShell 后再次执行本脚本。" -ForegroundColor Yellow
    exit 1
}

$steamDomains = @(
    "store.steampowered.com",
    "login.steampowered.com",
    "help.steampowered.com",
    "api.steampowered.com",
    "checkout.steampowered.com",
    "avatars.steamstatic.com",
    "clan.steamstatic.com",
    "store.cloudflare.steamstatic.com",
    "store.akamai.steamstatic.com",
    "community.cloudflare.steamstatic.com",
    "community.akamai.steamstatic.com",
    "cdn.cloudflare.steamstatic.com",
    "steamcdn-a.akamaihd.net",
    "steamcommunity-a.akamaihd.net",
    "media.steampowered.com",
    "steamcommunity.com"
)

$fallbackIps = @{
    "store.steampowered.com" = @("23.15.142.182", "23.49.104.48", "104.89.103.51")
    "avatars.steamstatic.com" = @("151.101.79.52", "151.101.1.52", "23.2.16.11")
    "cdn.cloudflare.steamstatic.com" = @("23.2.16.11", "23.2.16.32", "104.16.29.34")
    "steamcdn-a.akamaihd.net" = @("23.208.12.167", "23.208.12.156", "23.49.104.59")
    "steamcommunity.com" = @("104.89.103.51", "23.49.104.48", "23.33.92.19")
}

if (-not (Test-Path $HostsPath)) {
    Write-ErrMsg "未找到 hosts 文件: $HostsPath"
    exit 1
}

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

$rawText = Get-Content $HostsPath -Raw -Encoding UTF8
if (-not $rawText) { $rawText = "" }
$allLines = $rawText -split "`r?`n"

# 清理历史 Steam 记录
function Clean-SteamHosts($lines) {
    $cleaned = @()
    $removed = 0
    $inBlock = $false
    $domainSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($d in $steamDomains) { [void]$domainSet.Add($d) }

    foreach ($line in $lines) {
        $trim = $line.Trim()
        if ($trim -like "# === Steam [Hh]osts*") {
            $inBlock = $true
            $removed++
            continue
        }
        if ($inBlock) {
            if ($trim -like "# === End Steam [Hh]osts*") {
                $inBlock = $false
            }
            $removed++
            continue
        }
        if ($trim -eq "" -or $trim.StartsWith("#")) {
            $cleaned += $line
            continue
        }
        $parts = $trim -split "\s+"
        $matched = $false
        for ($i = 1; $i -lt $parts.Length; $i++) {
            if ($domainSet.Contains($parts[$i])) {
                $matched = $true
                break
            }
        }
        if ($matched) {
            $removed++
            continue
        }
        $cleaned += $line
    }
    return @($cleaned, $removed)
}

# 纯清理模式
if ($Clean) {
    $cleanRes = Clean-SteamHosts $allLines
    $cleanedLines = $cleanRes[0]
    $removedCount = $cleanRes[1]

    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $bakFile = Join-Path $BackupDir "hosts_before_clean_$ts.bak"
    Copy-Item $HostsPath $bakFile -Force
    Write-Info "已备份当前 hosts 至: $bakFile"

    $finalStr = ($cleanedLines -join "`r`n") + "`r`n"
    [System.IO.File]::WriteAllText($HostsPath, $finalStr, [System.Text.UTF8Encoding]::new($false))
    Write-Success "成功清除 $removedCount 条 Steam hosts 历史记录！"
    Clear-DnsClientCache
    Write-Info "已刷新 Windows DNS 解析缓存。"
    exit 0
}

# DoH 解析
function Resolve-DoH($domain) {
    $endpoints = @(
        "https://doh.pub/resolve?name=$domain&type=A",
        "https://dns.alidns.com/resolve?name=$domain&type=A"
    )
    $ips = @()
    foreach ($url in $endpoints) {
        try {
            $resp = Invoke-RestMethod -Uri $url -TimeoutSec 3 -Headers @{ "Accept" = "application/dns-json" }
            if ($resp.Answer) {
                foreach ($ans in $resp.Answer) {
                    if ($ans.type -eq 1 -and $ans.data) {
                        $ipStr = $ans.data.ToString().Trim()
                        # 严格 IPv4 校验
                        [System.Net.IPAddress]$parsed = $null
                        if ([System.Net.IPAddress]::TryParse($ipStr, [ref]$parsed)) {
                            if ($parsed.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and -not $ipStr.StartsWith("127.") -and -not $ipStr.StartsWith("192.168.") -and -not $ipStr.StartsWith("10.")) {
                                $ips += $ipStr
                            }
                        }
                    }
                }
            }
            if ($ips.Count -gt 0) { break }
        } catch {
            continue
        }
    }
    if ($ips.Count -eq 0 -and $fallbackIps.ContainsKey($domain)) {
        $ips = $fallbackIps[$domain]
    }
    return $ips | Select-Object -Unique
}

# TCP 443 测速
function Test-Latency($ip, $timeoutMs = 1200) {
    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $client = [System.Net.Sockets.TcpClient]::new()
        $asyncResult = $client.BeginConnect($ip, 443, $null, $null)
        $success = $asyncResult.AsyncWaitHandle.WaitOne($timeoutMs, $false)
        $sw.Stop()
        if ($success -and $client.Connected) {
            $client.EndConnect($asyncResult)
            $client.Close()
            return [math]::Round($sw.Elapsed.TotalMilliseconds, 1)
        }
        $client.Close()
        return $null
    } catch {
        return $null
    }
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " 🚀 Steam Hosts 一键防污染优选与配置脚本 (PowerShell)" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Info "开始防污染 DoH 解析与 TCP 443 延迟优选 (共 $($steamDomains.Count) 个核心域名)..."

$optimized = @()
$idx = 1
foreach ($domain in $steamDomains) {
    $cands = Resolve-DoH $domain
    $bestIp = $null
    $minLatency = 999999

    foreach ($ip in $cands) {
        $ms = Test-Latency $ip
        if ($ms -ne $null -and $ms -lt $minLatency) {
            $minLatency = $ms
            $bestIp = $ip
        }
    }

    if ($bestIp -ne $null) {
        $optimized += [PSCustomObject]@{
            Domain  = $domain
            IP      = $bestIp
            Latency = $minLatency
        }
        Write-Host "  [$($idx.ToString().PadLeft(2))/$($steamDomains.Count)]  $($domain.PadRight(36)) -> $($bestIp.PadRight(15)) ($("${minLatency}ms".PadLeft(7)))" -ForegroundColor Green
    } else {
        Write-Host "  [$($idx.ToString().PadLeft(2))/$($steamDomains.Count)] ⚠️ $($domain.PadRight(36)) -> 节点连接超时" -ForegroundColor Yellow
    }
    $idx++
}

if ($optimized.Count -eq 0) {
    Write-ErrMsg "未能测出任何可用的 Steam 节点，请检查网络！"
    exit 2
}

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$header = "# === Steam Hosts (Auto-Optimized at $ts) ==="
$footer = "# === End Steam Hosts ==="
$newLines = @()
foreach ($item in $optimized) {
    $newLines += "$($item.IP.PadRight(16))`t$($item.Domain.PadRight(36)) # $($item.Latency)ms"
}

if ($DryRun) {
    Write-Host "`n[INFO] 当前为预览模式 (-DryRun)，未写入 hosts 文件。推荐条目如下：" -ForegroundColor Cyan
    Write-Host "------------------------------------------------------------------"
    Write-Host $header
    $newLines | ForEach-Object { Write-Host $_ }
    Write-Host $footer
    Write-Host "------------------------------------------------------------------"
    exit 0
}

Write-Info "`n正在安全备份并写入系统 hosts..."
$tsFile = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $BackupDir "hosts_$tsFile.bak"
Copy-Item $HostsPath $backupPath -Force
Write-Info "现存 hosts 已自动备份至: $backupPath"

$cleanRes = Clean-SteamHosts $allLines
$cleanedLines = $cleanRes[0]
$removedCount = $cleanRes[1]
if ($removedCount -gt 0) {
    Write-Info "已自动清理 $removedCount 条历史 Steam 记录"
}

$finalLines = $cleanedLines + "" + $header + $newLines + $footer + ""
$finalText = ($finalLines -join "`r`n") + "`r`n"

[System.IO.File]::WriteAllText($HostsPath, $finalText, [System.Text.UTF8Encoding]::new($false))
Write-Success "hosts 写入完成: $HostsPath"

# 自动刷新 DNS 缓存
try {
    Clear-DnsClientCache
    Write-Success "Windows DNS 解析缓存已自动刷新！"
} catch {
    ipconfig /flushdns | Out-Null
    Write-Success "Windows DNS 解析缓存已自动刷新 (ipconfig /flushdns)！"
}

Write-Host "`n==================================================================" -ForegroundColor Cyan
Write-Host "🎉 优化完成！Steam 商店、图片、CDN 与登录加速已生效。" -ForegroundColor Green
Write-Host "💡 提示：若访问 steamcommunity.com 被阻断，系国内运营商针对社区 TLS" -ForegroundColor Yellow
Write-Host "   SNI 的重置，需配合 Steam++ / Watt Toolkit 本地代理。" -ForegroundColor Yellow
Write-Host "==================================================================" -ForegroundColor Cyan
