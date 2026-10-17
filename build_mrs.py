#!/usr/bin/env python3
"""
构建金融规则集 mrs 文件（mihomo 二进制格式）。

按地区拆分两组，每组含 domain + ipcidr 两个 mrs：
  cn-finance-*  中国内地券商（同花顺/东方财富/华泰）→ 建议 DIRECT
  hk-finance-*  香港及海外券商（富途/长桥/老虎/雪球/盈透/Schwab）→ 建议代理

用法: python3 build_mrs.py [规则集目录]

mihomo 内核查找顺序：
  1. 环境变量 MIHOMO_PATH
  2. 项目根目录 ./mihomo
  3. PATH 中的 mihomo / clash-meta
  4. 自动下载到项目根目录
"""
import os
import subprocess
import sys
import ipaddress
import platform

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "rule-provider")
MIHOMO_VER = "v1.19.32"

SETS = [
    ("cn", "cn-finance-rules.list", "cn-finance"),
    ("hk", "hk-finance-rules.list", "hk-finance"),
]


def find_mihomo():
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


def load(list_path):
    domains, ips = [], []
    for line in open(list_path):
        r = line.strip()
        if not r or r.startswith("#"):
            continue
        if r.split(",")[0] == "IP-CIDR":
            cidr = r.split(",", 1)[1].replace(",no-resolve", "")
            try:
                ips.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                pass
        else:
            domains.append(r)
    return domains, ips


def main():
    ok_all = True
    print(f"规则集目录：{BASE}\n")
    for side, listname, prefix in SETS:
        path = os.path.join(BASE, listname)
        if not os.path.exists(path):
            print(f"  ! 缺少源文件 {listname}，跳过 {side}")
            ok_all = False
            continue

        domains, ips = load(path)
        collapsed = list(ipaddress.collapse_addresses(ips))

        dp = f"{BASE}/_{side}.domains.payload"
        ipp = f"{BASE}/_{side}.ips.payload"
        with open(dp, "w") as f:
            f.write("\n".join(domains) + "\n")
        with open(ipp, "w") as f:
            f.write("\n".join(str(n) for n in collapsed) + "\n")

        for behavior, payload, out in [
            ("domain", dp, f"{BASE}/{prefix}-domains.mrs"),
            ("ipcidr", ipp, f"{BASE}/{prefix}-ipcidr.mrs"),
        ]:
            if os.path.exists(out):
                os.remove(out)
            subprocess.run(
                [MIHOMO, "convert-ruleset", behavior, "text", payload, out],
                capture_output=True, text=True,
            )
            ok = os.path.exists(out) and os.path.getsize(out) > 0
            ok_all = ok_all and ok
            print(f"  {side}/{behavior:8s} {'OK ' if ok else 'FAIL'}  "
                  f"{os.path.getsize(out) if ok else 0:>6} bytes  {os.path.basename(out)}")

        for p in (dp, ipp):
            os.remove(p)
        print(f"       域名 {len(domains)} 条，IP 段 {len(ips)} → 合并后 {len(collapsed)} 条\n")

    if not ok_all:
        print("存在失败项，请检查上方输出")
        return 1
    print("全部构建完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
