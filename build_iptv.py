#!/usr/bin/env python3
"""
从 IPTV 播放列表生成 mihomo 规则集（iptv-rules）。

用法:
  python3 build_iptv.py [播放列表文件...]

  不带参数时默认读以下两份（本机 Downloads 目录）:
    GNTV.m3u        国际频道 + 港台频道 + 地方频道
    港澳台.txt      频道名,URL 格式的大量备用源

  播放列表可以是 .m3u（#EXTINF 后跟 URL）或 频道名,URL 的 txt。

产出（rule-provider/）:
  iptv-sources.txt   从播放列表提取的全部 host 清单（含裸 IP），供追溯
  iptv-rules.yaml    规则集（推荐引用这个）
  iptv-rules.list    clash 传统格式
  iptv-domains.mrs   域名 mrs
  iptv-ipcidr.mrs    IP 段 mrs

为什么要 IP-CIDR：播放列表里有大量「裸 IP 直连」源（如
http://211.72.174.95:8116/0.ts），域名规则覆盖不到，只能按 IP 段兜底。
TUN 模式下这些连接由 IP 规则接管，所以 ipcidr 那份也要挂。

域名规约规则（决定用整域还是保留完整子域）：
  - 一般情况取注册域（php.jdshipin.com → jdshipin.com），聚合服务的
    多个子域靠这一条全覆盖
  - CDN/云平台保留完整子域：*.cloudfront.net / *.akamaized.net /
    *.amazonaws.com / *.cloudflare.net —— 整域太宽，会卷进无关流量
  - www.youtube.com、raw.githubusercontent.com 保留完整：配置里已有
    YouTube / GitHub 规则集接管整域，IPTV 只抢直播源那一条
  - 多段后缀（com.hk / com.cn / sh.cn / com.tr 等）取三段，
    否则 hkcable.com.hk 会被砍成 com.hk、setv.sh.cn 被砍成 sh.cn
"""
import os
import re
import subprocess
import sys
import ipaddress
from collections import OrderedDict

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT) if os.path.basename(ROOT) == "scripts" else ROOT
BASE = os.path.join(REPO, "rule-provider")

DEFAULT_SOURCES = [
    os.path.expanduser("~/Downloads/GNTV.m3u"),
    os.path.expanduser("~/Downloads/港澳台.txt"),
]

# 多段公共后缀：这些的最后两段不是注册域，要取三段
MULTI_SUFFIX = {
    "com.hk", "com.cn", "com.tw", "com.mo", "net.cn", "org.cn", "gov.cn",
    "co.uk", "co.jp", "com.tr", "com.au", "com.sg", "com.my",
}
# 中国省级行政区二级域（sh.cn / gd.cn ...），取四段或三段
PROVINCE_CN = {
    "bj", "tj", "he", "sx", "nm", "ln", "jl", "hl", "js", "zj", "ah", "fj",
    "jx", "sd", "ha", "hb", "hn", "gd", "gx", "hi", "sc", "gz", "yn", "xz",
    "sn", "gs", "qh", "nx", "xj", "sh", "cq",
}
# 整域太宽、必须保留完整子域的平台
KEEP_FULL_SUFFIX = (".cloudfront.net", ".akamaized.net", ".amazonaws.com",
                    ".cloudflare.net")
# 配置里已有整域规则集接管，这里只保留直播源那一条
KEEP_FULL_EXACT = {"www.youtube.com", "raw.githubusercontent.com"}


def registrable(host):
    """把主机名规约成规则里用的后缀。"""
    if host in KEEP_FULL_EXACT:
        return host
    if host.endswith(KEEP_FULL_SUFFIX):
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    tail2 = ".".join(parts[-2:])
    if tail2 in MULTI_SUFFIX:
        return ".".join(parts[-3:])
    if parts[-1] == "cn" and parts[-2] in PROVINCE_CN:
        return ".".join(parts[-3:]) if len(parts) >= 3 else host
    return tail2


def load_urls(path):
    """从 m3u 或 频道名,URL 的 txt 里取出所有 URL。"""
    urls = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "," in s and not re.match(r"^[a-z]+://", s, re.I):
            s = s.split(",", 1)[1].strip()
        if re.match(r"^[a-z]+://", s, re.I) or s.startswith("video://"):
            urls.append(s)
    return urls


def main():
    srcs = sys.argv[1:] or [p for p in DEFAULT_SOURCES if os.path.exists(p)]
    if not srcs:
        print("没有找到播放列表文件，用法：python3 build_iptv.py <文件...>")
        return 1
    missing = [p for p in srcs if not os.path.exists(p)]
    if missing:
        print("文件不存在，已中止：")
        for p in missing:
            print(f"  ✗ {p}")
        return 1

    urls = []
    for p in srcs:
        n = len(load_urls(p))
        urls += load_urls(p)
        print(f"  {os.path.basename(p):20s} {n:4d} 条 URL")
    print(f"  合计 {len(urls)} 条 URL")

    hosts, ips, bad = OrderedDict(), [], 0
    for u in urls:
        u = re.sub(r"^video://", "", u)       # video://https:// 双协议前缀
        m = re.match(r"^[a-z]+://([^/:]+)", u, re.I)
        if not m:
            bad += 1
            continue
        h = m.group(1).lower().rstrip(".")
        try:
            ipaddress.ip_address(h)
            if h not in ips:
                ips.append(h)
        except ValueError:
            hosts[registrable(h)] = hosts.get(registrable(h), 0) + 1

    if bad:
        print(f"  ! {bad} 条 URL 无法解析出 host，已跳过")
    if not hosts:
        print("没提取到任何域名，疑似文件格式不对，已中止。")
        return 1

    # 裸 IP 归并成网段（同 /24 的合成 /24，减少规则条数）
    nets = sorted(ipaddress.collapse_addresses(
        [ipaddress.ip_network(f"{ip}/32") for ip in ips]),
        key=lambda n: int(n.network_address))
    print(f"\n域名 {len(hosts)} 个，裸 IP {len(ips)} 个 → 归并后 {len(nets)} 个网段")

    os.makedirs(BASE, exist_ok=True)
    with open(f"{BASE}/iptv-sources.txt", "w") as f:
        f.write("# IPTV 播放列表提取的 host 清单\n")
        f.write("# 域名 " + str(len(hosts)) + " 个 / 裸 IP " + str(len(ips)) + " 个\n\n")
        for h, c in sorted(hosts.items(), key=lambda x: (-x[1], x[0])):
            f.write(f"{h}\t{c}\n")
        f.write("\n# 裸 IP\n")
        for ip in sorted(ips, key=lambda x: ipaddress.ip_address(x)):
            f.write(f"{ip}\n")

    groups = [
        ("IPTV 聚合 / 直播源（主要）",
         ["freetv.fun", "jdshipin.com", "jiduo.me", "m16tv.cfd", "aktv.top",
          "iill.top", "163189.xyz", "iptv8k.top", "amagi.tv", "rr.kg",
          "rakuten.tv", "yximgs.com", "1678520.xyz", "cc.cd", "indevs.in",
          "wouu.net", "ysift55.xyz", "4666888.xyz", "itv888.vip", "ottb.xyz",
          "epg.pw", "faintv.com", "xmzb.xyz", "xiangxiws.vip", "vpstv.net",
          "kylintv.tv", "live4play.uk", "jydjd.top", "ottera.tv", "tvfix.org",
          "hls-gateway.vpstv.net"]),
        ("国际新闻 / 广电官方",
         ["cgtn.com", "ifeng.com", "rttv.com", "france24.com", "getaj.net",
          "nhkworld.jp", "warnermediacdn.com", "mediacdn.ru", "corusdigitaldev.com",
          "italkbbtv.com", "wcetv.com", "hkcable.com.hk", "hkstv.tv", "hkdvb.com",
          "ctm.net", "amtb.cn", "bozztv.com", "onrender.com", "tubi.video"]),
        ("国内地方频道（地区限制，必须走代理）",
         ["cztv.com", "cztvcloud.com", "nmtv.cn", "nntv.cn", "gztv.com",
          "nbs.cn", "hebtv.com", "bestv.cn", "0593tv.cn", "67890123.cn",
          "shaoxing.com.cn", "wsrtv.com.cn", "111yao.cn", "hystudio.cn",
          "terrykang.cn", "51kandianshi.com", "iiiya.cn", "yiandrive.com",
          "yryyj.site", "senpay23.com", "ohoyee.com", "iactive-clink.com",
          "its-newid.net", "cloudcdn.me", "cnstream.top", "rocketdns.info",
          "trexlive.me", "dyndns.tv", "light-ott.net", "osvs.asia",
          "asuscomm.com", "dpdns.org", "ignorelist.com", "iok.la", "mine.nu",
          "filegear-sg.me", "cdn-o2.me", "ghp.ci", "707626.xyz", "anren.live",
          "com.tr"]),
    ]
    used = set()
    lines = [
        "# IPTV 分流规则集（港澳台 + 国际 + 国内地方频道）",
        "# 来源：本机播放列表 GNTV.m3u + 港澳台.txt 提取",
        f"# 统计：DOMAIN {len(hosts)} / IP-CIDR {len(nets)}（裸 IP {len(ips)} 个归并而来）",
        "",
        "# 用途：这些源大多有地区限制或走 UDP/RTP，直连看不了，",
        "#       统一走美国 VPS（无限流量）这类出口。",
        "# 注意：规则必须放在 GeoCN / MATCH 之前——国内地方台的域名",
        "#       在 ChinaMax 里，被直连规则接走就看不到了。",
        "",
        "rules:",
    ]
    for title, order in groups:
        items = [d for d in order if d in hosts and d not in used]
        rest = [d for d in sorted(hosts) if d not in used
                and d not in order]
        if items:
            used.update(items)
            lines.append(f"  # ---- {title} ----")
            lines += [f"  - DOMAIN-SUFFIX,{d}" for d in items]
    rest = [d for d in sorted(hosts) if d not in used]
    if rest:
        lines.append("  # ---- 其它（含 CDN 具体分配域名，整域太宽不能规约）----")
        lines += [f"  - DOMAIN-SUFFIX,{d}" for d in rest]

    lines.append("  # ---- 裸 IP 源（域名规则覆盖不到，按 IP 段兜底）----")
    lines += [f"  - IP-CIDR,{n},no-resolve" for n in nets]

    with open(f"{BASE}/iptv-rules.yaml", "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    with open(f"{BASE}/iptv-rules.list", "w") as f:
        f.write("\n".join(
            f"DOMAIN-SUFFIX,{d}" for d in hosts
        ) + "\n")
        f.write("\n".join(f"IP-CIDR,{n},no-resolve" for n in nets) + "\n")

    print(f"\n重建 mrs：")
    r = subprocess.run([sys.executable, os.path.join(REPO, "build_mrs.py")],
                       capture_output=True, text=True)
    for line in r.stdout.strip().splitlines():
        print("  " + line)
    if r.returncode != 0:
        print(r.stderr[:800])
        return 1

    d = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                       capture_output=True, text=True).stdout.strip()
    if not d:
        print("\n无变化，无需提交。")
        return 0
    subprocess.run(["git", "add", "-A"], cwd=REPO)
    subprocess.run(
        ["git", "commit", "-m",
         f"build: 更新 IPTV 规则集（域名 {len(hosts)} / 网段 {len(nets)}）\n\n"
         f"来源：{' / '.join(os.path.basename(p) for p in srcs)}"],
        cwd=REPO,
    )
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
