#!/usr/bin/env python3
import argparse
import os
import platform
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


def parse_hosts(hosts_path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    content = hosts_path.read_text(encoding="utf-8", errors="ignore")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        ip = parts[0]
        for domain in parts[1:]:
            mapping[domain] = ip
    return mapping


def system_resolve(domain: str) -> list[str]:
    try:
        import socket

        infos = socket.getaddrinfo(domain, None)
        ips = []
        for info in infos:
            ip = info[4][0]
            if ":" in ip:
                continue
            ips.append(ip)
        return sorted(set(ips))
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Steam hosts entries.")
    parser.add_argument("--hosts", dest="hosts_path", default=str(default_hosts_path()))
    args = parser.parse_args()

    hosts_path = Path(args.hosts_path)
    if not hosts_path.exists():
        print(f"[ERROR] hosts not found: {hosts_path}", file=sys.stderr)
        return 1

    hosts_map = parse_hosts(hosts_path)
    ok = True
    for domain in STEAM_DOMAINS:
        host_ip = hosts_map.get(domain)
        resolved_ips = system_resolve(domain)
        if not host_ip:
            print(f"[WARN] hosts missing: {domain}")
            ok = False
            continue
        if host_ip in resolved_ips:
            print(f"[OK] {domain} -> {host_ip}")
        else:
            print(f"[WARN] {domain} hosts={host_ip} resolved={resolved_ips or 'none'}")
            ok = False

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
