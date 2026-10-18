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
    ("meta", "meta-muse-rules.list", "meta-muse"),
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
    """读入规则 list，分成域名规则和 IP 规则。

    mrs 的 domain 行为对 payload 格式有严格要求：
      精确域名  → 裸域名          eastmoney.com
      域名后缀  → 带 + 前缀       +.eastmoney.com
    直接写 `DOMAIN-SUFFIX,eastmoney.com` 会被当成字面域名，生成一个
    永远匹配不上的废 trie（文件还会变大一倍）——这是之前踩过的坑。
    DOMAIN-KEYWORD 无法进 domain trie，只能留给 yaml 版本。
    """
    domains, ips = [], []
    keywords = []
    for line in open(list_path):
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
        elif kind == "DOMAIN-SUFFIX":
            domains.append("+." + r.split(",", 1)[1])
        elif kind == "DOMAIN":
            domains.append(r.split(",", 1)[1])
        elif kind == "DOMAIN-KEYWORD":
            keywords.append(r.split(",", 1)[1])
    return domains, ips, keywords


def main():
    ok_all = True
    print(f"规则集目录：{BASE}\n")
    for side, listname, prefix in SETS:
        path = os.path.join(BASE, listname)
        if not os.path.exists(path):
            print(f"  ! 缺少源文件 {listname}，跳过 {side}")
            ok_all = False
            continue

        domains, ips, keywords = load(path)
        collapsed = list(ipaddress.collapse_addresses(ips))

        dp = f"{BASE}/_{side}.domains.payload"
        ipp = f"{BASE}/_{side}.ips.payload"
        with open(dp, "w") as f:
            f.write("\n".join(domains) + "\n")
        with open(ipp, "w") as f:
            f.write("\n".join(str(n) for n in collapsed) + "\n")

        for behavior, payload, empty, fname in [
            ("domain", dp, not domains, "domains"),
            ("ipcidr", ipp, not collapsed, "ipcidr"),
        ]:
            out = f"{BASE}/{prefix}-{fname}.mrs"
            # 该类型没有任何规则时不产出 mrs（并清理残留），
            # 避免出现一个 0 条目的空壳文件被路由器拉下去。
            if empty:
                if os.path.exists(out):
                    os.remove(out)
                print(f"  {side}/{behavior:8s} SKIP  无条目，跳过  "
                      f"{os.path.basename(out)}")
                continue
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
            if os.path.exists(p):
                os.remove(p)
        print(f"       域名 {len(domains)} 条，IP 段 {len(ips)} → 合并后 {len(collapsed)} 条\n")

    if not ok_all:
        print("存在失败项，请检查上方输出")
        return 1
    print("全部构建完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
