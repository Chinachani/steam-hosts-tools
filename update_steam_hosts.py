#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


STEAM_DOMAINS = [
    "api.steampowered.com",
    "steamcommunity.com",
    "store.steampowered.com",
    "help.steampowered.com",
    "login.steampowered.com",
    "steamcdn-a.akamaihd.net",
    "cdn.cloudflare.steamstatic.com",
]


def default_hosts_path() -> Path:
    system = platform.system().lower()
    if system == "windows":
        return Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def has_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def resolve_with_dig(domain: str, dns: str) -> list[str]:
    if not has_cmd("dig"):
        return []
    try:
        out = subprocess.check_output(["dig", "@"+dns, "+short", domain], text=True, timeout=5)
    except Exception:
        return []
    return [line.strip() for line in out.splitlines() if line.strip() and ":" not in line]


def resolve_with_nslookup(domain: str, dns: str) -> list[str]:
    if not has_cmd("nslookup"):
        return []
    try:
        out = subprocess.check_output(["nslookup", domain, dns], text=True, timeout=5)
    except Exception:
        return []
    ips = []
    for line in out.splitlines():
        line = line.strip()
        if line.lower().startswith("address:"):
            ip = line.split(":", 1)[1].strip()
            if ip and ":" not in ip:
                ips.append(ip)
    return ips


def resolve_system(domain: str) -> list[str]:
    try:
        out = subprocess.check_output(["getent", "ahosts", domain], text=True, timeout=5)
        ips = []
        for line in out.splitlines():
            parts = line.split()
            if parts and "." in parts[0]:
                ips.append(parts[0])
        return sorted(set(ips))
    except Exception:
        return []


def resolve_domain(domain: str, dns_servers: list[str]) -> list[str]:
    for dns in dns_servers:
        ips = resolve_with_dig(domain, dns)
        if not ips:
            ips = resolve_with_nslookup(domain, dns)
        if ips:
            return sorted(set(ips))
    # Fallback to system resolver
    ips = resolve_system(domain)
    return sorted(set(ips))


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Steam hosts entries (cross-platform).")
    parser.add_argument("--hosts", dest="hosts_path", default=str(default_hosts_path()))
    parser.add_argument("--backup-dir", dest="backup_dir", default="./hosts_backup")
    parser.add_argument(
        "--dns",
        dest="dns_servers",
        default="8.8.8.8,1.1.1.1",
        help="Comma-separated DNS servers for resolution (uses dig/nslookup if available).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hosts_path = Path(args.hosts_path)
    backup_dir = Path(args.backup_dir)
    dns_servers = [x.strip() for x in args.dns_servers.split(",") if x.strip()]

    if not hosts_path.exists():
        print(f"[ERROR] hosts not found: {hosts_path}", file=sys.stderr)
        return 1

    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"hosts_{ts}.bak"
    shutil.copy2(hosts_path, backup_path)
    print(f"[INFO] backup created: {backup_path}")

    content = hosts_path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    filtered = []
    removed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            filtered.append(line)
            continue
        is_steam = any(f" {d}" in f" {stripped} " for d in STEAM_DOMAINS)
        if is_steam:
            removed += 1
            continue
        filtered.append(line)
    print(f"[INFO] removed {removed} existing Steam host entries")

    new_entries = []
    for domain in STEAM_DOMAINS:
        ips = resolve_domain(domain, dns_servers)
        if not ips:
            print(f"[WARN] failed to resolve {domain} via DNS {', '.join(dns_servers)}")
            continue
        for ip in ips:
            new_entries.append(f"{ip}\t{domain}")

    header = f"# === Steam hosts (auto-generated) {ts} ==="
    footer = "# === End Steam hosts ==="
    final_lines = filtered + [header] + new_entries + [footer]

    if args.dry_run:
        print("[INFO] dry-run enabled. Proposed entries:")
        for line in new_entries:
            print(line)
        return 0

    hosts_path.write_text("\n".join(final_lines) + "\n", encoding="utf-8")
    print(f"[INFO] hosts updated: {hosts_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
