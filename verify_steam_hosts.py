#!/usr/bin/env python3
"""
Steam Hosts 配置与连通性验证工具 (Steam Hosts Verifier)
特点：
1. 快速读取系统 hosts 中的 Steam 条目
2. 逐一发起 TCP 443 端口真机握手测活与延迟检测
3. 格式化输出健康度报告与诊断建议
"""

import argparse
import os
import platform
import re
import socket
import sys
import time
from pathlib import Path

STEAM_DOMAINS = [
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
    "steamcommunity.com",
]


def get_default_hosts_path() -> Path:
    if platform.system().lower() == "windows":
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        return Path(system_root) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def parse_hosts_file(hosts_path: Path) -> dict[str, str]:
    """解析 hosts 文件，精准提取域名对应的首选生效 IP"""
    domain_to_ip: dict[str, str] = {}
    if not hosts_path.exists():
        return domain_to_ip

    content = hosts_path.read_text(encoding="utf-8", errors="ignore")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = re.split(r"\s+", stripped)
        if len(parts) < 2:
            continue
        ip = parts[0]
        for domain in parts[1:]:
            clean_domain = domain.strip().lower()
            # Windows hosts 只以首条记录生效，已存在的不被覆盖
            if clean_domain not in domain_to_ip:
                domain_to_ip[clean_domain] = ip
    return domain_to_ip


def test_connectivity(ip: str, port: int = 443, timeout: float = 1.5) -> tuple[bool, float]:
    """测试 TCP 端口连通性及耗时"""
    try:
        t0 = time.perf_counter()
        sock = socket.create_connection((ip, port), timeout=timeout)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        sock.close()
        return True, round(elapsed_ms, 1)
    except Exception:
        return False, 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="校验系统 hosts 中的 Steam 配置与实际连通性")
    parser.add_argument(
        "--hosts",
        dest="hosts_path",
        default=str(get_default_hosts_path()),
        help="目标 hosts 文件路径 (默认自动识别系统路径)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.5,
        help="TCP 探测超时时间（秒，默认 1.5s）",
    )
    args = parser.parse_args()

    hosts_path = Path(args.hosts_path)
    if not hosts_path.exists():
        print(f"[ERROR] 找不到 hosts 文件: {hosts_path}", file=sys.stderr)
        return 1

    hosts_map = parse_hosts_file(hosts_path)

    print("=" * 76)
    print(" 🔍 Steam Hosts 连通性与生效状态校验报告")
    print("=" * 76)
    print(f"{'域名 (Domain)':<36} | {'Hosts 绑定 IP':<16} | {'延迟':<9} | {'连通状态'}")
    print("-" * 76)

    total = len(STEAM_DOMAINS)
    ok_count = 0
    missing_count = 0
    unreachable_count = 0

    for domain in STEAM_DOMAINS:
        ip = hosts_map.get(domain)
        if not ip:
            missing_count += 1
            print(f"{domain:<36} | {'(未配置)':<16} | {'-':<9} | ⚠️  未配置条目")
            continue

        connected, latency = test_connectivity(ip, 443, timeout=args.timeout)
        if connected:
            ok_count += 1
            print(f"{domain:<36} | {ip:<16} | {f'{latency}ms':<9} |  可正常直连")
        else:
            unreachable_count += 1
            print(f"{domain:<36} | {ip:<16} | {'超时':<9} | ❌ 连接失败/超时")

    print("=" * 76)
    print(f"📊 探测统计：总计 {total} 个核心域名， 正常 {ok_count} 个，❌ 失败 {unreachable_count} 个，⚠️ 未配置 {missing_count} 个")

    if missing_count > 0 or unreachable_count > 0:
        print("\n💡 建议：可运行以下命令重新测速并写入最优节点：")
        if platform.system().lower() == "windows":
            print("   以管理员身份运行：python update_steam_hosts.py")
        else:
            print("   运行：sudo python3 update_steam_hosts.py")
        return 2

    print("\n🎉 全部 Steam 核心域名配置正常，且 443 端口网络通畅！")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
