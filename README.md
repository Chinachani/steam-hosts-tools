# Steam Hosts Tools (Steam Hosts 一键防污染优选工具)

独立的 Steam hosts 自动化优选与配置工具集（纯标准库实现，零第三方依赖，跨平台支持 Windows / Linux / macOS）。

---

## ✨ 核心特性

- 🛡️ **加密 DoH 防污染解析**：采用 DNS-over-HTTPS (DoH) 加密查询（支持 DNSPod / AliDNS / Cloudflare），彻底避开国内 UDP 53 端口的 DNS 投毒与伪造 IP。
- ⚡ **TCP 443 毫秒级并发测速**：对解析出的所有候选 CDN 边缘节点（Akamai / Cloudflare / Fastly）并发发起 TCP 443 握手测活，自动剔除超时/丢包节点，仅为每个域名优选**延迟最低、连接最快**的节点。
- 🧹 **安全无损 Hosts 管理**：
  - 严格校验 IPv4 地址合法性，拦截局域网 IP 与 CNAME 域名误写；
  - 正则清洗历史 Steam 条目（完美兼容空格与制表符），杜绝重复膨胀；
  - 写入前自动在 `hosts_backup/` 生成带时间戳的完整备份。
- 🔄 **自动刷新系统 DNS 缓存**：修改完成后自动调用系统级命令刷新 DNS 缓存（Windows `ipconfig /flushdns`、Linux `resolvectl`、macOS `mDNSResponder`），即刻生效。
- 🌐 **全方位现代 Steam 域名覆盖**：包含商店（Store）、登录鉴权、结算（Checkout）、玩家头像（Avatars）、活动公告（Clan）、多节点图片与资源 CDN。

---

## 📂 工具一览

| 脚本文件 | 说明 | 推荐平台 |
| :--- | :--- | :--- |
| `update_steam_hosts.py` | **推荐**。跨平台优选与更新脚本（并发测速、DoH 防污染、自动刷新缓存） | Windows / Linux / macOS |
| `verify_steam_hosts.py` | 连通性校验脚本，检测当前 hosts 中的 Steam 配置与实际 443 端口网络通畅度 | 全平台 |
| `update_steam_hosts.ps1` | Windows 原生 PowerShell 版本，无需额外环境即可运行 | Windows 10 / 11 |

---

## 🚀 使用指南

### 1. Python 版本（全平台推荐）

> **注意**：修改系统 `hosts` 文件需要管理员/root 权限。

#### 预览推荐节点（不修改文件）
```bash
python3 update_steam_hosts.py --dry-run
```

#### 执行优选并写入系统 hosts
- **Windows**（在以「管理员身份运行」的终端中执行）：
  ```cmd
  python update_steam_hosts.py
  ```
- **Linux / macOS**：
  ```bash
  sudo python3 update_steam_hosts.py
  ```

#### 清除所有 Steam 记录恢复默认
```bash
sudo python3 update_steam_hosts.py --clean
```

#### 校验 hosts 是否生效与连通性
```bash
python3 verify_steam_hosts.py
```

---

### 2. Windows PowerShell 版本

在 Windows 搜索框搜索 `PowerShell`，右键点击**以管理员身份运行**：

```powershell
# 执行优选并更新
.\update_steam_hosts.ps1

# 仅预览
.\update_steam_hosts.ps1 -DryRun

# 清除所有 Steam 记录
.\update_steam_hosts.ps1 -Clean
```

---

## 🛠️ 常用参数说明

`update_steam_hosts.py` 支持以下命令行参数：

- `--dry-run`：仅测速并输出推荐的 hosts 配置，不写入任何系统文件。
- `--clean`：安全移除 hosts 中现存的所有 Steam 条目。
- `--timeout <秒数>`：TCP 测速超时时间（默认 `1.2` 秒）。
- `--hosts <路径>`：自定义 hosts 路径（默认自动识别系统路径）。
- `--backup-dir <目录>`：指定备份文件目录（默认 `./hosts_backup`）。
- `--verbose` / `-v`：输出每个 DoH 接口的详细解析情况与测速日志。
- `--no-flush`：写入后不自动刷新系统 DNS 缓存。

---

## 💡 关于 Steam 社区（steamcommunity.com）的说明

- **商店与静态资源 CDN**（`store.steampowered.com`、`*.steamstatic.com`、`steamcdn-a.akamaihd.net` 等）：
  写入优选的 Akamai / Cloudflare 官方边缘节点后，可**免代理直连秒开**，大幅提升图片加载速度与商店浏览流畅度。
- **社区主站**（`steamcommunity.com`）：
  由于中国大陆防火墙（GFW）针对 `steamcommunity.com` 的 TLS 握手部署了 **SNI 关键字阻断（发送 RST 复位包）**，仅靠修改 hosts 无法直接解决社区个人资料、创意工坊或好友动态无法加载的问题。如需完全访问社区，建议搭配 [Steam++ (Watt Toolkit)](https://steampp.net/) 等本地代理工具使用。

---

## 📄 开源许可

MIT License
