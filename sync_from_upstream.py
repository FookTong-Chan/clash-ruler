#!/usr/bin/env python3
"""
从上游 koo17173/rule-set 实时抓取金融规则 → 按机构归类拆分 → 重建 mrs → 有变化则推送。

产出两组规则集（每组含 domain + ipcidr 两个 mrs）：
  cn-finance-*  中国内地券商：同花顺、东方财富、华泰        → 建议 DIRECT
  hk-finance-*  香港及海外券商：富途/moomoo、长桥、老虎、
                雪球、盈透、Schwab、华泰HK                 → 建议代理

用法:
  python3 sync_from_upstream.py            # 抓取 + 归类 + 构建 + 推送
  python3 sync_from_upstream.py --dry-run  # 只抓取归类，不推送
  python3 sync_from_upstream.py --no-push  # 构建并本地提交，但不 push（CI 用）

安全策略：任一上游文件抓取失败、或某组结果为空时，直接中止，
不改动本地文件、不提交——绝不允许空规则集覆盖已有内容。
"""
import argparse
import base64
import ipaddress
import os
import shutil
import subprocess
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT) if os.path.basename(ROOT) == "scripts" else ROOT
BASE = os.path.join(REPO, "rule-provider")

UPSTREAM = "koo17173/rule-set"
REF = "main"

SOURCES = [
    "BrokerHK",
    "HK_Broker.conf",
    "BrokerCN",
    "BrokerHT",
    "Stocks.list",
    "StocksHK.list",
]
EXCLUDED = ["Others.list", "Talkatone&T-mobile.list", "UKMobile.list"]

# 过宽的裸 TLD 后缀，会误伤无关站点，剔除
DROP_SUFFIXES = {"18.cn", "18.com.cn"}

RAW = "https://raw.githubusercontent.com/{}/{}/{}"


# ============================================================
# 机构归属识别：决定一条规则进「内地组」还是「香港组」
# ============================================================
ENTITY_PATTERNS = [
    # ---- 香港 / 海外券商 ----
    ("富途·moomoo", ["futunn", "futubull", "futuhk", "futufin", "futuholdings",
                  "futuniuniu", "futuesop", "futuinc", "futuin", "futuhn",
                  "futustatic", "fututrade", "fututrustee", "futuone", "futuclean",
                  "futusign", "futusg", "futuweb", "futusecurities", "futumkt",
                  "futuapi", "futuau", "futuchain", "futu.sg", "futu.au",
                  "futu.link", "futu0", "futu1", "futu2", "futu3",
                  "futu4", "futu5", "futu6", "futu7", "futu8", "futu9",
                  "ftnndn", "qtlcdn", "futures.hk", "moomoo",
                  "play-analytics", "appsflyersdk",
                  "futu.com", "futu.cn", "futuhongkong", "futuhkapp"]),
    ("长桥", ["longbridge", "longport", "lbkrs", "lbctrl", "wbrks", "lbkg",
             "lb-static"]),
    ("老虎", ["itiger", "tigerbrokers", "tigerfintech", "tigerbbs", "skytigris",
             "tradeup", "iotaskyt", "laohu8", "xiaohu8", "zhijianfengyi"]),
    ("雪球", ["snowball-x", "snowballsecurities", "snbsecurities"]),
    ("盈透", ["interactivebrokers", "ibkr"]),
    ("Schwab", ["schwab"]),
    # 内地券商的香港子公司：统一走代理（与华泰HK 同规则）
    ("华泰HK", ["htsc.com.hk"]),
    ("东方财富HK", ["emsec.hk"]),
    # ---- 中国内地券商 ----
    ("同花顺", ["10jqka", "iwencai", "hexin", "hexun", "ths", "hithink",
              "zhifutech", "aicubes", "voiceclub", "gtimg", "sinajs", "hxkba",
              "yongginbao", "wosms", "0033.com", "soumoney", "ticang",
              "51ifind", "5ifund", "yingfund", "huntgold", "touzime",
              "tdx.com.cn", "gw.com.cn", "ip-api"]),
    ("东方财富", ["eastmoney", "dfcfw", "dfcfs", "caifutong", "caimi",
               "dingqibao", "dongfanglicaishi", "guba", "haitunzhibo",
               "huoqibao", "langke", "samacn", "tiantianfunds", "txjhqh",
               "uufund", "xzsec", "zhaiba", "zhongcaisuo", "1234567", "95021"]),
    ("华泰", ["htsc", "zhangle", "htzq", "zhangleglobal", "ihtfin",
             "cmpassport", "finet", "roadshowing"]),
]

HK_ENTITIES = {"富途·moomoo", "长桥", "老虎", "雪球", "盈透", "Schwab",
               "华泰HK", "东方财富HK"}

# ============================================================
# 本地补充域名：上游规则集漏掉、但实测必须走对应分流的域名。
# 每次同步都会自动合并，不会被上游覆盖。
# ============================================================
EXTRA_RULES = {
    # 盈透证券现用主域是 ibkr.com（官网/登录/API 全在它下面），
    # 上游只有老的 interactivebrokers.com。
    # 缺它时 ibkr.com 会掉进 MATCH 兜底、随机走全球节点（实测命中 🌍全球备用）。
    "hk": {"suffix": ["ibkr.com", "ibkr.com.hk"]},
}

# 中国大陆运营商 / 云厂商网段（华泰、同花顺的国内服务器）。
# 不在其中的 IP 段一律归入香港/海外组。
CN_IP_RANGES = [
    "180.101.0.0/16", "222.190.0.0/16", "221.226.0.0/16", "218.2.0.0/16",
    "122.96.0.0/16", "153.3.0.0/16", "157.0.0.0/16",
    "120.195.0.0/16", "218.206.0.0/16", "223.112.0.0/16",
    "47.106.0.0/16", "120.79.0.0/16",
    "124.70.0.0/16", "113.44.0.0/16",
    "122.9.0.0/16", "221.236.0.0/16",
]
CN_NETS = [ipaddress.ip_network(c) for c in CN_IP_RANGES]


def classify_domain(domain):
    """返回域名所属机构名，无法识别返回 None。"""
    d = domain.lower()
    for entity, pats in ENTITY_PATTERNS:
        for p in pats:
            if p in d:
                return entity
    return None


def classify_ip(cidr):
    """IP 段是否位于中国大陆。"""
    net = ipaddress.ip_network(cidr, strict=False)
    return any(net.subnet_of(cn) for cn in CN_NETS)


def new_box():
    return {"exact": OrderedDict(), "suffix": OrderedDict(),
            "keyword": OrderedDict(), "ipcidr": OrderedDict()}


def fetch(name, retries=3):
    """从上游拉取单个规则文件原文。

    依次尝试三条通道，任一成功即返回：
      1. gh api      —— 本地有认证时最快
      2. curl        —— CI 环境（raw 直连不被墙）
      3. urllib      —— 最后兜底
    """
    last = "unknown error"
    for attempt in range(1, retries + 1):
        # 通道 1：gh api（需已认证）
        gh = shutil.which("gh")
        if gh:
            r = subprocess.run(
                [gh, "api", f"repos/{UPSTREAM}/contents/{name}?ref={REF}",
                 "--jq", ".content"],
                capture_output=True, text=True, timeout=90,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    return base64.b64decode(r.stdout.strip()).decode("utf-8")
                except Exception:
                    pass
            # gh 存在但未认证/失败 → 落到下一个通道

        # 通道 2：curl 直连 raw
        r = subprocess.run(
            ["curl", "-fsSL", "--max-time", "60", RAW.format(UPSTREAM, REF, name)],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        last = (r.stderr or r.stdout or "").strip().splitlines()
        last = last[-1][:200] if last else "curl failed"

        # 通道 3：urllib
        try:
            import urllib.request
            with urllib.request.urlopen(
                    RAW.format(UPSTREAM, REF, name), timeout=60) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            last = f"urllib: {e}"

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
    return exact, suffix, keyword, ipcidr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="不提交不推送")
    ap.add_argument("--no-push", action="store_true",
                    help="提交但不 push（GitHub Actions 用）")
    args = ap.parse_args()

    print(f"上游：{UPSTREAM}@{REF}")
    print(f"抓取 {len(SOURCES)} 个金融文件（排除 {len(EXCLUDED)} 个非金融文件）\n")

    entities = OrderedDict()
    unclassified = []
    failures = []

    for name in SOURCES:
        try:
            text = fetch(name)
        except Exception as e:
            failures.append((name, str(e)))
            continue
        e, s, k, i = parse(text)
        n = 0
        for d in e + s + k:
            ent = classify_domain(d)
            if ent is None:
                unclassified.append(d)
                continue
            box = entities.setdefault(ent, new_box())
            if d in e:
                box["exact"][d] = True
            elif d in s:
                box["suffix"][d] = True
            else:
                box["keyword"][d] = True
            n += 1
        for c in i:
            key = "__CN_IP__" if classify_ip(c) else "__HK_IP__"
            entities.setdefault(key, new_box())["ipcidr"][c] = True
            n += 1
        print(f"  {name:18s} 归类 {n:3d} 条")

    # 抓取失败即中止，保留本地文件不动
    if failures:
        print("\n抓取失败，已中止（未改动任何本地文件）：")
        for name, err in failures:
            print(f"  ✗ {name}: {err}")
        return 1

    if unclassified:
        print(f"\n  ! {len(unclassified)} 条域名未能识别机构，已剔除：")
        for d in sorted(set(unclassified)):
            print(f"      {d}")

    # ---- 清洗 ----
    for box in entities.values():
        for d in list(box["exact"]):
            box["suffix"].pop(d, None)
        for d in DROP_SUFFIXES:
            box["suffix"].pop(d, None)

    # ---- 按地区汇总成两组 ----
    groups = {"cn": new_box(), "hk": new_box()}
    print("\n机构归属：")
    for ent, box in entities.items():
        if ent == "__CN_IP__":
            side = "cn"
        elif ent == "__HK_IP__":
            side = "hk"
        else:
            side = "hk" if ent in HK_ENTITIES else "cn"
        if not ent.startswith("__"):
            label = "香港/海外" if side == "hk" else "中国内地"
            print(f"  [{label}] {ent:12s} {sum(len(v) for v in box.values()):3d} 条")
        for kind in box:
            groups[side][kind].update(box[kind])

    # ---- 合并本地补充域名（上游缺失、实测必需）----
    for side, extra in EXTRA_RULES.items():
        for kind, items in extra.items():
            for d in items:
                groups[side][kind][d.lower()] = True
                print(f"\n  + 本地补充 [{side}] {kind}:{d.lower()}")

    collapsed_by_side = {}
    for side, label in (("cn", "中国内地"), ("hk", "香港/海外")):
        g = groups[side]
        nets = [ipaddress.ip_network(c, strict=False) for c in g["ipcidr"]]
        collapsed = list(ipaddress.collapse_addresses(nets))
        collapsed_by_side[side] = collapsed
        print(f"\n{label}合计：exact={len(g['exact'])} suffix={len(g['suffix'])} "
              f"keyword={len(g['keyword'])} ipcidr={len(collapsed)}"
              f"（输入 {len(nets)}，去冗余 {len(nets)-len(collapsed)}）")
        if not (g["exact"] or g["suffix"]):
            print(f"\n{label}组为空，疑似上游内容异常，已中止。")
            return 1

    # ---- 写出（两组各自一份 yaml + list）----
    os.makedirs(BASE, exist_ok=True)
    for side, prefix, label in (("cn", "cn-finance", "中国内地券商"),
                                ("hk", "hk-finance", "香港及海外券商")):
        g = groups[side]
        collapsed = sorted(str(n) for n in collapsed_by_side[side])

        lines = [
            f"# 金融规则集 - {label}",
            f"# 同步自 https://github.com/{UPSTREAM} @ {REF}",
            "#   " + " / ".join(SOURCES),
            f"# 统计：DOMAIN {len(g['exact'])} / DOMAIN-SUFFIX {len(g['suffix'])} / "
            f"DOMAIN-KEYWORD {len(g['keyword'])} / IP-CIDR {len(collapsed)}",
            "",
            "rules:",
            "  # ---- 精确域名（行情/交易/OpenAPI 端点） ----",
        ]
        lines += [f"  - DOMAIN,{d}" for d in g["exact"]]
        lines += ["", "  # ---- 域名后缀（券商客户端与官网） ----"]
        lines += [f"  - DOMAIN-SUFFIX,{d}" for d in g["suffix"]]
        if g["keyword"]:
            lines += ["", "  # ---- 域名关键词（富途 moomoo 兜底） ----"]
            lines += [f"  - DOMAIN-KEYWORD,{k}" for k in g["keyword"]]
        lines += ["", "  # ---- IP 段 ----"]
        lines += [f"  - IP-CIDR,{c},no-resolve" for c in collapsed]

        plain = (
            [f"DOMAIN,{d}" for d in g["exact"]]
            + [f"DOMAIN-SUFFIX,{d}" for d in g["suffix"]]
            + [f"DOMAIN-KEYWORD,{k}" for k in g["keyword"]]
            + [f"IP-CIDR,{c},no-resolve" for c in collapsed]
        )
        with open(f"{BASE}/{prefix}-rules.yaml", "w") as f:
            f.write("\n".join(lines).rstrip() + "\n")
        with open(f"{BASE}/{prefix}-rules.list", "w") as f:
            f.write("\n".join(plain) + "\n")

    # ---- 重建 mrs ----
    print("\n重建 mrs：")
    r = subprocess.run([sys.executable, os.path.join(REPO, "build_mrs.py")],
                       capture_output=True, text=True)
    for line in r.stdout.strip().splitlines():
        print("  " + line)
    if r.returncode != 0:
        print(r.stderr[:800])
        return 1

    if args.dry_run:
        print("\n--dry-run：不提交不推送")
        return 0

    # ---- 有变化才提交 ----
    d = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                       capture_output=True, text=True).stdout.strip()
    if not d:
        print("\n上游无变化，无需提交。")
        return 0

    print("\n检测到变化：")
    print(d)
    subprocess.run(["git", "add", "-A"], cwd=REPO)
    cn, hk = groups["cn"], groups["hk"]
    subprocess.run(
        ["git", "commit", "-m",
         f"sync: 同步上游 {UPSTREAM}@{REF}（按机构拆分）\n\n"
         f"内地券商：exact {len(cn['exact'])} / suffix {len(cn['suffix'])} / "
         f"keyword {len(cn['keyword'])}\n"
         f"港外券商：exact {len(hk['exact'])} / suffix {len(hk['suffix'])} / "
         f"keyword {len(hk['keyword'])}"],
        cwd=REPO,
    )

    if args.no_push:
        print("\n--no-push：已本地提交，未推送（由 CI 工作流负责推送）")
        return 0

    p = subprocess.run(["git", "push"], cwd=REPO, capture_output=True, text=True)
    if p.returncode == 0:
        print("已推送到 origin/main ✓")
    else:
        print("推送失败：")
        print((p.stdout + p.stderr)[:600])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
