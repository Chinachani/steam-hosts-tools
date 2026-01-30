$ErrorActionPreference = "Stop"

param(
    [string]$HostsPath = "$env:SystemRoot\System32\drivers\etc\hosts",
    [string]$BackupDir = "$PSScriptRoot\hosts_backup",
    [string[]]$DnsServers = @("8.8.8.8", "1.1.1.1"),
    [switch]$DryRun
)

function Write-Info($msg) { Write-Host "[INFO] $msg" }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }

$steamDomains = @(
    "api.steampowered.com",
    "steamcommunity.com",
    "store.steampowered.com",
    "help.steampowered.com",
    "login.steampowered.com",
    "steamcdn-a.akamaihd.net",
    "cdn.cloudflare.steamstatic.com",
    "steamstatic.com"
)

if (-not (Test-Path $HostsPath)) {
    throw "Hosts file not found: $HostsPath"
}

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $BackupDir "hosts_$timestamp.bak"
Copy-Item $HostsPath $backupPath -Force
Write-Info "Backup created: $backupPath"

$lines = Get-Content $HostsPath -Raw -Encoding UTF8
if (-not $lines) { $lines = "" }

$lineList = $lines -split "`r?`n"
$filtered = @()
$removed = 0
foreach ($line in $lineList) {
    $trim = $line.Trim()
    if ($trim -eq "" -or $trim.StartsWith("#")) {
        $filtered += $line
        continue
    }
    $isSteam = $false
    foreach ($d in $steamDomains) {
        if ($trim -match "(^|\s)${d}(\s|$)") {
            $isSteam = $true
            break
        }
    }
    if ($isSteam) {
        $removed++
        continue
    }
    $filtered += $line
}
Write-Info "Removed $removed existing Steam host entries."

$newEntries = @()
foreach ($domain in $steamDomains) {
    $resolved = $false
    foreach ($dns in $DnsServers) {
        try {
            $records = Resolve-DnsName -Name $domain -Server $dns -Type A -ErrorAction Stop
            $ips = $records | Where-Object { $_.IPAddress } | Select-Object -ExpandProperty IPAddress -Unique
            if ($ips) {
                foreach ($ip in $ips) {
                    $newEntries += "$ip`t$domain"
                }
                $resolved = $true
                break
            }
        } catch {
            continue
        }
    }
    if (-not $resolved) {
        Write-Warn "Failed to resolve $domain via DNS: $($DnsServers -join ', ')"
    }
}

$header = "# === Steam hosts (auto-generated) $timestamp ==="
$footer = "# === End Steam hosts ==="

$final = @()
$final += $filtered
$final += $header
$final += $newEntries
$final += $footer

if ($DryRun) {
    Write-Info "DryRun enabled. Proposed entries:"
    $newEntries | ForEach-Object { Write-Host $_ }
    exit 0
}

$finalText = ($final -join "`r`n") + "`r`n"
Set-Content -Path $HostsPath -Value $finalText -Encoding UTF8
Write-Info "Hosts updated: $HostsPath"
