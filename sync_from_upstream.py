#!/usr/bin/env python3
"""
从上游 koo17173/rule-set 实时抓取金融规则 → 合并去重 → 重建 mrs → 有变化则推送。

与 scripts/merge_finance.py 的区别：
  merge_finance.py   规则硬编码在常量里，只用于一次性生成/留档
  本脚本              每次运行都从上游拉取最新内容

用法:
  python3 sync_from_upstream.py            # 抓取 + 合并 + 构建 + 推送
  python3 sync_from_upstream.py --dry-run  # 只抓取合并，不推送（看差异）

安全策略：任一上游文件抓取失败、或合并结果为空时，直接中止，
不改动本地文件、不提交——绝不允许空规则集覆盖已有内容。
"""
import argparse
import ipaddress
import os
import subprocess
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT) if os.path.basename(ROOT) == "scripts" else ROOT
BASE = os.path.join(REPO, "rule-provider")

UPSTREAM = "koo17173/rule-set"
REF = "main"

# 参与合并的上游文件（金融相关）
SOURCES = [
    "BrokerHK",
    "HK_Broker.conf",
    "BrokerCN",
    "BrokerHT",
    "Stocks.list",
    "StocksHK.list",
]
# 明确排除：非金融内容
EXCLUDED = ["Others.list", "Talkatone&T-mobile.list", "UKMobile.list"]

# 过宽的裸 TLD 后缀，会误伤无关站点，合并时剔除
DROP_SUFFIXES = {"18.cn", "18.com.cn"}

RAW = "https://raw.githubusercontent.com/{}/{}/{}"


def fetch(name, retries=3):
    """从上游拉取单个规则文件原文。

    用 curl 子进程而非 urllib：沙箱会拦截 Python urllib 的
    出站连接（Connection reset by peer），curl 不受影响，
    且自动尊重 http_proxy/https_proxy 环境变量。
    """
    url = RAW.format(UPSTREAM, REF, name)
    last = "unknown error"
    for attempt in range(1, retries + 1):
        r = subprocess.run(
            ["curl", "-fsSL", "--max-time", "60", url],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        last = (r.stderr or r.stdout or "").strip().splitlines()
        last = last[-1][:200] if last else "unknown error"
        print(f"  ! {name} 第 {attempt}/{retries} 次抓取失败：{last}")
    raise RuntimeError(last)


def parse(text):
    """把上游的 classical 格式解析成 (exact, suffix, keyword, ipcidr)。"""
    exact, suffix, keyword, ipcidr = [], [], [], []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(",")]
        kind = parts[0].upper()
        if kind == "DOMAIN" and len(parts) >= 2:
            exact.append(parts[1].lower())
        elif kind == "DOMAIN-SUFFIX" and len(parts) >= 2:
            suffix.append(parts[1].lower())
        elif kind == "DOMAIN-KEYWORD" and len(parts) >= 2:
            keyword.append(parts[1].lower())
        elif kind == "IP-CIDR" and len(parts) >= 2:
            ipcidr.append(parts[1])
        # IP-CIDR6 / 其它类型直接忽略
    return exact, suffix, keyword, ipcidr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="不推送，只报告差异")
    args = ap.parse_args()

    print(f"上游：{UPSTREAM}@{REF}")
    print(f"抓取 {len(SOURCES)} 个金融文件（排除 {len(EXCLUDED)} 个非金融文件）\n")

    exact, suffix, keyword, ipcidr = OrderedDict(), OrderedDict(), OrderedDict(), OrderedDict()
    per_file = {}
    failures = []

    for name in SOURCES:
        try:
            text = fetch(name)
        except Exception as e:
            # 抓取失败即中止：绝不能用空规则集覆盖本地内容
            failures.append((name, str(e)))
            continue
        e, s, k, i = parse(text)
        for x in e:
            exact[x] = True
        for x in s:
            suffix[x] = True
        for x in k:
            keyword[x] = True
        for x in i:
            ipcidr[x] = True
        per_file[name] = len(e) + len(s) + len(k) + len(i)
        print(f"  {name:18s} exact={len(e):3d} suffix={len(s):3d} keyword={len(k)} ipcidr={len(i):3d}")

    # ---- 抓取失败即中止，保留本地文件不动 ----
    if failures:
        print("\n抓取失败，已中止（未改动任何本地文件）：")
        for name, err in failures:
            print(f"  ✗ {name}: {err}")
        return 1

    # ---- 清洗 ----
    for d in list(exact):
        suffix.pop(d, None)          # 精确项不从后缀集合重复出现
    for d in DROP_SUFFIXES:
        suffix.pop(d, None)          # 去掉过宽后缀

    # ---- IP 段规整 ----
    nets = []
    for c in ipcidr:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            pass
    collapsed = list(ipaddress.collapse_addresses(nets))
    dropped_ip = len(nets) - len(collapsed)

    total = len(exact) + len(suffix) + len(keyword) + len(collapsed)
    print(f"\n合并结果：exact={len(exact)} suffix={len(suffix)} "
          f"keyword={len(keyword)} ipcidr={len(collapsed)}（去冗余 {dropped_ip}）")
    print(f"总计 {total} 条")

    if total == 0:
        print("\n合并结果为空，疑似上游内容异常，已中止（未改动任何本地文件）。")
        return 1

    # ---- 写出 ----
    os.makedirs(BASE, exist_ok=True)
    yaml_lines = [
        "# 金融规则集 / Financial Ruleset",
        f"# 同步自 https://github.com/{UPSTREAM} @ {REF}",
        "#   " + " / ".join(SOURCES),
        "# 覆盖：富途·moomoo、长桥、老虎、雪球、盈透、Schwab、同花顺、东方财富、华泰",
        f"# 统计：DOMAIN {len(exact)} / DOMAIN-SUFFIX {len(suffix)} / "
        f"DOMAIN-KEYWORD {len(keyword)} / IP-CIDR {len(collapsed)}",
        "",
        "rules:",
        "  # ---- 精确域名（行情/交易/OpenAPI 端点） ----",
    ]
    yaml_lines += [f"  - DOMAIN,{d}" for d in exact]
    yaml_lines += ["", "  # ---- 域名后缀（券商客户端与官网） ----"]
    yaml_lines += [f"  - DOMAIN-SUFFIX,{d}" for d in suffix]
    if keyword:
        yaml_lines += ["", "  # ---- 域名关键词（富途 moomoo 兜底） ----"]
        yaml_lines += [f"  - DOMAIN-KEYWORD,{k}" for k in keyword]
    yaml_lines += ["", "  # ---- IP 段（券商行情/交易服务器） ----"]
    yaml_lines += [f"  - IP-CIDR,{c},no-resolve" for c in sorted(ipcidr)]

    plain = (
        [f"DOMAIN,{d}" for d in exact]
        + [f"DOMAIN-SUFFIX,{d}" for d in suffix]
        + [f"DOMAIN-KEYWORD,{k}" for k in keyword]
        + [f"IP-CIDR,{c},no-resolve" for c in sorted(ipcidr)]
    )

    yaml_path = os.path.join(BASE, "finance-rules.yaml")
    list_path = os.path.join(BASE, "finance-rules.list")
    with open(yaml_path, "w") as f:
        f.write("\n".join(yaml_lines).rstrip() + "\n")
    with open(list_path, "w") as f:
        f.write("\n".join(plain) + "\n")

    # ---- 重建 mrs ----
    print("\n重建 mrs：")
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "build_mrs.py")],
        capture_output=True, text=True,
    )
    for line in r.stdout.strip().splitlines():
        print("  " + line)
    if r.returncode != 0:
        print(r.stderr[:500])
        return 1

    if args.dry_run:
        print("\n--dry-run：不提交不推送")
        return 0

    # ---- 有变化才推送 ----
    d = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                       capture_output=True, text=True).stdout.strip()
    if not d:
        print("\n上游无变化，无需推送。")
        return 0

    print("\n检测到变化：")
    print(d)
    subprocess.run(["git", "add", "-A"], cwd=REPO)
    subprocess.run(
        ["git", "commit", "-m",
         f"sync: 同步上游 {UPSTREAM}@{REF}\n\n"
         f"规则 {total} 条（exact {len(exact)} / suffix {len(suffix)} / "
         f"keyword {len(keyword)} / ipcidr {len(collapsed)}）"],
        cwd=REPO,
    )
    p = subprocess.run(["git", "push"], cwd=REPO, capture_output=True, text=True)
    if p.returncode == 0:
        print("已推送到 origin/main ✓")
    else:
        print("推送失败：")
        print((p.stdout + p.stderr)[:500])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())