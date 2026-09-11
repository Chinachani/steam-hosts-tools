#!/usr/bin/env python3
"""
Steam Hosts 一键优选与更新工具 (Cross-Platform Steam Hosts Optimizer)
特点：
1. 采用 DoH (DNS-over-HTTPS) 加密防污染解析，杜绝国内 UDP 53 端口 DNS 投毒
2. 全域名 TCP 443 端口并发测活与 RTT 延迟优选，自动剔除死链/丢包节点
3. 严格 IPv4 校验与局域网/CNAME 伪地址过滤
4. 智能 hosts 去重清洗，避免文件膨胀
5. 自动备份、权限检测、跨平台适配及自动刷新系统 DNS 缓存
"""

import argparse
import concurrent.futures
import ctypes
import datetime as dt
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# 现代 Steam 核心域名清单（涵盖商店、登录、API、头像、公告与各 CDN 资源）
STEAM_DOMAINS = [
    # 商店、结算与账户
    "store.steampowered.com",
    "login.steampowered.com",
    "help.steampowered.com",
    "api.steampowered.com",
    "checkout.steampowered.com",
    # 静态资源与图片 CDN (Akamai / Cloudflare / Fastly)
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
    # 社区主站 (注：国内大多省份存在针对 steamcommunity.com 的 TLS SNI 阻断，hosts 提供最佳直连节点)
    "steamcommunity.com",
]

# 加密 DoH 解析源（HTTPS 443 传输，GFW 无法通过 UDP 53 进行 DNS 投毒）
DOH_ENDPOINTS = [
    ("DNSPod", "https://doh.pub/resolve?name={domain}&type=A"),
    ("AliDNS", "https://dns.alidns.com/resolve?name={domain}&type=A"),
    ("Cloudflare", "https://cloudflare-dns.com/dns-query?name={domain}&type=A"),
    ("Google", "https://dns.google/resolve?name={domain}&type=A"),
]

# 备用优质 CDN IP 池（当本地所有 DNS 均不可用时的兜底节点）
FALLBACK_IPS = {
    "store.steampowered.com": ["23.15.142.182", "23.49.104.48", "104.89.103.51"],
    "avatars.steamstatic.com": ["151.101.79.52", "151.101.1.52", "23.2.16.11"],
    "cdn.cloudflare.steamstatic.com": ["23.2.16.11", "23.2.16.32", "104.16.29.34"],
    "steamcdn-a.akamaihd.net": ["23.208.12.167", "23.208.12.156", "23.49.104.59"],
    "steamcommunity.com": ["104.89.103.51", "23.49.104.48", "23.33.92.19"],
}


def is_admin() -> bool:
    """检查当前进程是否具有管理员 / root 权限"""
    try:
        if platform.system().lower() == "windows":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def get_default_hosts_path() -> Path:
    """获取系统默认 hosts 路径"""
    if platform.system().lower() == "windows":
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        return Path(system_root) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def is_valid_public_ipv4(ip_str: str) -> bool:
    """严格校验是否为合法的公网 IPv4 地址（排除私网、环回、多播与保留地址）"""
    try:
        ip = ipaddress.IPv4Address(ip_str.strip())
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except Exception:
        return False


def query_doh(domain: str, url_template: str, timeout: float = 2.5) -> list[str]:
    """通过 DoH 接口解析 A 记录"""
    url = url_template.format(domain=domain)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/dns-json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return []
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            answers = data.get("Answer", [])
            ips = []
            for ans in answers:
                # Type 1 = A 记录
                if ans.get("type") == 1 and "data" in ans:
                    raw_ip = str(ans["data"]).strip()
                    if is_valid_public_ipv4(raw_ip):
                        ips.append(raw_ip)
            return ips
    except Exception:
        return []


def resolve_domain_candidates(domain: str, verbose: bool = False) -> list[str]:
    """多源获取域名的候选 IP（并发查询多个 DoH 源并合并兜底池）"""
    candidate_set: set[str] = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(DOH_ENDPOINTS)) as executor:
        future_map = {
            executor.submit(query_doh, domain, template): name
            for name, template in DOH_ENDPOINTS
        }
        for future in concurrent.futures.as_completed(future_map):
            name = future_map[future]
            try:
                ips = future.result()
                if ips:
                    if verbose:
                        print(f"  [DoH] {domain} <- {', '.join(ips)} (from {name})")
                    candidate_set.update(ips)
            except Exception:
                pass

    # 兜底：若全解析失败，注入已知高可用节点
    if not candidate_set:
        for key, fb_ips in FALLBACK_IPS.items():
            if key in domain or domain in key:
                candidate_set.update(fb_ips)
                if verbose:
                    print(f"  [Fallback] {domain} <- 命中预设备用节点池: {fb_ips}")
                break

    return list(candidate_set)


def test_tcp_latency(ip: str, port: int = 443, timeout: float = 1.2) -> float | None:
    """测算目标 IP 在指定端口上的 TCP 连接握手延迟（毫秒），超时或失败返回 None"""
    try:
        start_time = time.perf_counter()
        sock = socket.create_connection((ip, port), timeout=timeout)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        sock.close()
        return round(elapsed_ms, 1)
    except Exception:
        return None


def select_best_ip(domain: str, candidate_ips: list[str], timeout: float = 1.2, verbose: bool = False) -> tuple[str, float] | None:
    """对候选 IP 进行并发测速，选出响应时间最短且稳定连接的最佳 IP"""
    if not candidate_ips:
        return None

    results: list[tuple[str, float]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(candidate_ips), 10)) as executor:
        future_to_ip = {
            executor.submit(test_tcp_latency, ip, 443, timeout): ip
            for ip in candidate_ips
        }
        for future in concurrent.futures.as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                latency = future.result()
                if latency is not None:
                    results.append((ip, latency))
                    if verbose:
                        print(f"  [Ping] {domain} -> {ip}: 443 端口握手成功 ({latency}ms)")
            except Exception:
                pass

    if not results:
        return None

    # 按延迟从小到大排序，选取最优 IP
    results.sort(key=lambda x: x[1])
    return results[0]


def flush_dns_cache():
    """根据操作系统自动刷新 DNS 解析缓存"""
    system = platform.system().lower()
    try:
        if system == "windows":
            subprocess.run(["ipconfig", "/flushdns"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[INFO] Windows DNS 缓存已自动刷新 (ipconfig /flushdns)")
        elif system == "darwin":
            subprocess.run(["killall", "-HUP", "mDNSResponder"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[INFO] macOS DNS 缓存已自动刷新")
        elif system == "linux":
            if shutil.which("resolvectl"):
                subprocess.run(["resolvectl", "flush-caches"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[INFO] Linux DNS 缓存已自动刷新 (resolvectl flush-caches)")
            elif shutil.which("systemd-resolve"):
                subprocess.run(["systemd-resolve", "--flush-caches"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[INFO] Linux DNS 缓存已自动刷新 (systemd-resolve --flush-caches)")
    except Exception as e:
        print(f"[WARN] 自动刷新 DNS 缓存提示: {e}，请手动尝试刷新系统 DNS")


def clean_existing_steam_hosts(lines: list[str]) -> tuple[list[str], int]:
    """安全清洗 hosts 内容，利用正则同时适配空格与制表符，精准移除历史 Steam 记录"""
    cleaned: list[str] = []
    removed_count = 0
    in_steam_block = False

    domain_set = set(STEAM_DOMAINS)

    for line in lines:
        stripped = line.strip()
        # 兼容处理自动生成的区块标识
        if stripped.startswith("# === Steam hosts") or stripped.startswith("# === Steam Hosts"):
            in_steam_block = True
            removed_count += 1
            continue
        if in_steam_block:
            if stripped.startswith("# === End Steam hosts") or stripped.startswith("# === End Steam Hosts"):
                in_steam_block = False
            removed_count += 1
            continue

        if not stripped or stripped.startswith("#"):
            cleaned.append(line)
            continue

        parts = re.split(r"\s+", stripped)
        # 检查是否包含 Steam 域名
        has_steam_domain = any(part in domain_set for part in parts[1:])
        if has_steam_domain:
            removed_count += 1
            continue

        cleaned.append(line)

    return cleaned, removed_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Steam Hosts 一键防污染优选与更新工具 (Steam Hosts Optimizer)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--hosts",
        dest="hosts_path",
        default=str(get_default_hosts_path()),
        help="目标 hosts 文件路径 (默认自动识别系统路径)",
    )
    parser.add_argument(
        "--backup-dir",
        dest="backup_dir",
        default="./hosts_backup",
        help="hosts 历史备份目录 (默认 ./hosts_backup)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.2,
        help="TCP 测速超时时间（秒，默认 1.2s）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅测试并输出推荐的 hosts 条目，不实际修改系统 hosts 文件",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="清理并移除 hosts 文件中所有已存在的 Steam 记录，恢复原始状态",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="输出详细诊断信息（包含每个 DoH 解析结果与所有候选 IP 测速）",
    )
    parser.add_argument(
        "--no-flush",
        action="store_true",
        help="写入后不自动刷新系统 DNS 缓存",
    )

    args = parser.parse_args()
    hosts_path = Path(args.hosts_path)
    backup_dir = Path(args.backup_dir)

    print("=" * 66)
    print(" 🚀 Steam Hosts 一键防污染优选与配置工具")
    print("=" * 66)

    # 1. 检查权限
    if not args.dry_run and not is_admin():
        print("[ERROR] 权限不足！修改 hosts 文件需要管理员权限 (Administrator / root)。", file=sys.stderr)
        if platform.system().lower() == "windows":
            print("[提示] 请右键以「管理员身份运行」打开 PowerShell / CMD 后重试。", file=sys.stderr)
        else:
            print("[提示] 请使用 sudo 执行：sudo python3 update_steam_hosts.py", file=sys.stderr)
        return 1

    if not hosts_path.exists():
        print(f"[ERROR] 找不到 hosts 文件: {hosts_path}", file=sys.stderr)
        return 1

    # 2. 读取并备份现存 hosts
    try:
        raw_content = hosts_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"[ERROR] 读取 hosts 文件失败: {e}", file=sys.stderr)
        return 1

    # 3. 纯清理模式
    if args.clean:
        cleaned_lines, removed = clean_existing_steam_hosts(raw_content.splitlines())
        if removed == 0:
            print("[INFO] 当前 hosts 中未检测到现存 Steam 记录，无需清理。")
            return 0

        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"hosts_before_clean_{ts}.bak"
        shutil.copy2(hosts_path, backup_path)
        print(f"[INFO] 备份已保存至: {backup_path}")

        newline = "\r\n" if platform.system().lower() == "windows" else "\n"
        final_text = newline.join(cleaned_lines) + newline
        hosts_path.write_text(final_text, encoding="utf-8")
        print(f"[SUCCESS] 成功移除 {removed} 条 Steam hosts 记录！")
        if not args.no_flush:
            flush_dns_cache()
        return 0

    # 4. 域名解析与测速优选
    print(f"[1/3] 开始防污染 DoH 解析并并发测速 (共 {len(STEAM_DOMAINS)} 个核心域名)...")
    optimized_entries: list[tuple[str, str, float]] = []

    def process_domain(d: str) -> tuple[str, str, float] | None:
        cands = resolve_domain_candidates(d, verbose=args.verbose)
        if not cands:
            return None
        best = select_best_ip(d, cands, timeout=args.timeout, verbose=args.verbose)
        if best:
            return (best[0], d, best[1])
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_domain = {executor.submit(process_domain, d): (i, d) for i, d in enumerate(STEAM_DOMAINS, start=1)}
        results_by_idx: dict[int, tuple[str, str, float] | None] = {}
        for future in concurrent.futures.as_completed(future_to_domain):
            i, d = future_to_domain[future]
            try:
                res = future.result()
                results_by_idx[i] = res
                if res:
                    ip, domain, latency = res
                    print(f"  [{i:>2}/{len(STEAM_DOMAINS)}]  {domain:<36} -> {ip:<15} ({latency:>5.1f}ms)")
                else:
                    print(f"  [{i:>2}/{len(STEAM_DOMAINS)}] ⚠️  {d:<36} -> 未获取可用节点")
            except Exception as e:
                print(f"  [{i:>2}/{len(STEAM_DOMAINS)}] ❌ {d:<36} -> 发生异常: {e}")

    # 按原始域名顺序排版
    for i in range(1, len(STEAM_DOMAINS) + 1):
        res = results_by_idx.get(i)
        if res:
            optimized_entries.append(res)

    if not optimized_entries:
        print("\n[ERROR] 未能测出任何可用的 Steam 节点，请检查网络连接！", file=sys.stderr)
        return 2

    # 5. 生成拟写入的 hosts 条目
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"# === Steam Hosts (Auto-Optimized at {ts}) ==="
    footer = "# === End Steam Hosts ==="

    formatted_lines: list[str] = []
    for ip, domain, latency in optimized_entries:
        # 对齐排版并标注测速延迟
        formatted_lines.append(f"{ip:<16}\t{domain:<36} # {latency}ms")

    if args.dry_run:
        print("\n[INFO] 当前为预览模式 (--dry-run)，未写入系统文件。推荐配置如下：")
        print("-" * 66)
        print(header)
        for line in formatted_lines:
            print(line)
        print(footer)
        print("-" * 66)
        return 0

    # 6. 执行备份与写入
    print("\n[2/3] 正在安全写入系统 hosts...")
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts_file = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"hosts_{ts_file}.bak"
    shutil.copy2(hosts_path, backup_path)
    print(f"[INFO] 现存 hosts 已自动备份至: {backup_path}")

    cleaned_lines, removed = clean_existing_steam_hosts(raw_content.splitlines())
    if removed > 0:
        print(f"[INFO] 已自动清除 {removed} 条历史 Steam 相关条目")

    final_lines = cleaned_lines + ["", header] + formatted_lines + [footer, ""]
    newline = "\r\n" if platform.system().lower() == "windows" else "\n"
    final_content = newline.join(final_lines)

    try:
        hosts_path.write_text(final_content, encoding="utf-8")
        print(f"[3/3] hosts 写入完成: {hosts_path}")
    except Exception as e:
        print(f"[ERROR] 写入 hosts 文件失败: {e}", file=sys.stderr)
        return 1

    # 7. 自动刷新 DNS 缓存
    if not args.no_flush:
        flush_dns_cache()

    print("\n" + "=" * 66)
    print("🎉 优化完成！Steam 商店、静态图片、CDN 及登录加速已生效。")
    print("💡 温馨提示：")
    print("   1. 商店与图片 CDN 可大幅提升访问与加载速度；")
    print("   2. 若访问 steamcommunity.com 提示连接重置，属于国内运营商对社区")
    print("      TLS SNI 的阻断机制，需配合 Steam++ / Watt Toolkit 等本地代理工具。")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
