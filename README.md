# steam-hosts-tools

独立的 Steam hosts 工具集（与插件无关，可单独使用）。

## 脚本
- `update_steam_hosts.py` 跨平台更新 hosts（推荐）
- `update_steam_hosts.ps1` Windows PowerShell 版本
- `verify_steam_hosts.py` 校验 hosts 是否生效（IPv4）

## 用法示例
```
# 预览（不写入）
python3 update_steam_hosts.py --dry-run

# 更新 hosts（需要 root/管理员）
sudo python3 update_steam_hosts.py --dns 223.5.5.5,119.29.29.29,8.8.8.8

# 校验是否生效
python3 verify_steam_hosts.py
```

说明：修改 hosts 需要管理员权限。Docker 环境请以 root 执行或挂载宿主机 hosts。
