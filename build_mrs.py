#!/usr/bin/env python3
"""
生成金融规则集 mrs 文件（mihomo 二进制格式）。

用法: python3 build_mrs.py [输出目录]

mihomo 内核查找顺序：
  1. 环境变量 MIHOMO_PATH
  2. 项目根目录 ./mihomo
  3. PATH 中的 mihomo / clash-meta
  4. 自动下载到项目根目录（darwin-arm64 / linux-amd64 等）
"""
import os
import subprocess
import sys
import ipaddress
import platform

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "rule-provider")
LIST = f"{BASE}/finance-rules.list"

MIHOMO_VER = "v1.19.32"


def find_mihomo():
    """定位 mihomo 内核，找不到就下载一个。"""
    cand = []
    if os.environ.get("MIHOMO_PATH"):
        cand.append(os.environ["MIHOMO_PATH"])
    cand.append(os.path.join(ROOT, "mihomo"))
    for name in ("mihomo", "clash-meta"):
        cand.append(os.path.join("/opt/homebrew/bin", name))
        cand.append(os.path.join("/usr/local/bin", name))

    for c in cand:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c

    for name in ("mihomo", "clash-meta"):
        r = subprocess.run(["which", name], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()

    return download_mihomo()


def download_mihomo():
    """按当前平台下载 mihomo 到项目根目录。"""
    machine = platform.machine()
    osname = {"darwin": "darwin", "linux": "linux"}.get(
        platform.system().lower(), platform.system().lower())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(machine, "amd64")
    fname = f"mihomo-{osname}-{arch}-{MIHOMO_VER}.gz"
    url = f"https://github.com/MetaCubeX/mihomo/releases/download/{MIHOMO_VER}/{fname}"
    dest = os.path.join(ROOT, "mihomo")

    print(f"未找到 mihomo 内核，正在下载：{url}")
    import urllib.request, gzip, shutil
    with urllib.request.urlopen(url, timeout=120) as r, open(dest + ".gz", "wb") as f:
        shutil.copyfileobj(r, f)
    with gzip.open(dest + ".gz", "rb") as gz, open(dest, "wb") as out:
        shutil.copyfileobj(gz, out)
    os.remove(dest + ".gz")
    os.chmod(dest, 0o755)
    print(f"已就绪：{dest}")
    return dest


MIHOMO = find_mihomo()

# ---- 读入合并后的规则 ----
domains, ips = [], []
for line in open(LIST):
    r = line.strip()
    if not r or r.startswith("#"):
        continue
    kind = r.split(",")[0]
    if kind == "IP-CIDR":
        cidr = r.split(",", 1)[1].replace(",no-resolve", "")
        try:
            ips.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            pass
    else:
        domains.append(r)

# ---- IP 段合并去重（去掉被更宽网段覆盖的）----
collapsed = list(ipaddress.collapse_addresses(ips))
removed = len(ips) - len(collapsed)

# ---- 写纯 payload 文件（mrs 要求：domain 保留 TYPE 前缀，ipcidr 只需纯 CIDR）----
dom_payload = f"{BASE}/_domains.payload"
ip_payload = f"{BASE}/_ips.payload"

with open(dom_payload, "w") as f:
    f.write("\n".join(domains) + "\n")
with open(ip_payload, "w") as f:
    f.write("\n".join(str(n) for n in collapsed) + "\n")

# ---- 转换 ----
results = {}
for behavior, payload, out in [
    ("domain", dom_payload, f"{BASE}/finance-domains.mrs"),
    ("ipcidr", ip_payload, f"{BASE}/finance-ipcidr.mrs"),
]:
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run(
        [MIHOMO, "convert-ruleset", behavior, "text", payload, out],
        capture_output=True, text=True,
    )
    ok = os.path.exists(out) and os.path.getsize(out) > 0
    results[out] = ok
    print(f"  {behavior:8s} {'OK ' if ok else 'FAIL'}  {os.path.getsize(out) if ok else 0:>6} bytes  {os.path.basename(out)}")
    if not ok:
        print("   ", (r.stdout + r.stderr).strip()[:200])

for p in (dom_payload, ip_payload):
    os.remove(p)

print(f"\n域名规则 {len(domains)} 条")
print(f"IP 段    {len(ips)} 条 → 合并后 {len(collapsed)} 条（去冗余 {removed} 条）")
print(f"输出目录 {BASE}")