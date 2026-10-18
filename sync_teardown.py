#!/usr/bin/env python3
"""
Meta Muse 规则集生成器（一手逆向证据 + 二手整理互补）。

数据源：
  1. mahdi-salmanzade/meta-muse-teardown   主源。从 4 个 16-network-*.txt
     （cross-platform / macOS / iOS / Android）里正则提取静态分析出的 host，
     按角色归类。这是二进制逆向取证，比任何人工整理都细。
  2. juner922/muse-loon-rules              辅源。人工整理的 Loon 列表，
     补主源文本里没直接出现的裸域（atmeta.com / fb.com / whatsapp.net 等）。

产出（rule-provider/）：
  meta-muse-*      Meta 自有域（Muse 专用 + 账号/社交基础设施）→ 建议美国节点
  meta-muse-3p-*   第三方域（Google / Stripe / 连接器 OAuth / VM 网关等）→ 按需

用法:
  python3 sync_teardown.py            # 抓取 + 归类 + 构建 + 提交 + 推送
  python3 sync_teardown.py --dry-run  # 只抓取构建，不提交不推送
  python3 sync_teardown.py --no-push  # 本地提交但不 push（GitHub Actions 用）

安全策略：主源任一文件抓取失败、或主集为空时直接中止，不覆盖已有文件。
"""
import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT) if os.path.basename(ROOT) == "scripts" else ROOT
BASE = os.path.join(REPO, "rule-provider")
REF = "main"

TEARDOWN = "mahdi-salmanzade/meta-muse-teardown"
LOON = "juner922/muse-loon-rules"

# 逆向取证文件：三平台各一份 + 一份跨平台汇总
EVIDENCE = [
    "evidence/16-network-cross-platform.txt",
    "evidence/16-network-macos.txt",
    "evidence-ios/16-network-ios.txt",
    "evidence-android/16-network-android.txt",
]
LOON_FILE = "MuseAI.list"

RAW = "https://raw.githubusercontent.com/{}/{}/{}"

# ---- 正则提取的过滤条件 ----
# 取证文本里混着文件名（01-authenticity.txt）、RPC 方法名（activity.log）、
# 版本号（2.7.0-beta.1），只靠形状会收进来一大堆噪声，所以卡 TLD 白名单。
TLDS = {"com", "net", "org", "ai", "io", "dev", "me", "one", "xyz", "gov"}
HOST_RE = re.compile(
    r"(?<![A-Za-z0-9._*-])"
    r"((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24})"
    r"(?![A-Za-z0-9.-])"
)

# ---- 归类表 ----
# 命中这些后缀的 FQDN 规约成后缀本身（api.muse.ai → muse.ai），避免规则膨胀
META_COLLAPSE = [
    "muse.ai", "museai.com", "meta.ai", "metaaivm.com", "metaaiusercontent.com",
    "ecto1usercontent.com",
    "facebook.com", "facebook.net", "fbcdn.net", "fb.com", "fbsbx.com",
    "fbpigeon.com", "facebook-dns.com",
    "meta.com", "atmeta.com", "messenger.com", "threads.net",
    "instagram.com", "cdninstagram.com",
    "whatsapp.com", "whatsapp.net", "wa.me",
]
# 命中这些父域的 FQDN 保留精确域名（父域本身太宽，不能当后缀用）
META_EXACT_PARENT = ["fastly-edge.com", "privacy-gateway.cloudflare.com", "ecto1.ai"]

# 第三方：命中下面这些父域的 FQDN 规约成父域（accounts.google.com → google.com）。
# 不规约的话规则会碎成一地，规约过度又会误伤——只收"整个域都服务同一个用途"的。
THIRD_SUFFIXES = [
    "google.com", "googleapis.com", "gstatic.com", "googlesyndication.com",
    "stripe.com", "telegram.org", "t.me", "spotify.com", "firebaseio.com",
    "jsdelivr.net", "unpkg.com", "giphy.com", "akamai.com", "weather.gov",
    "healthex.io", "link.com", "onepeloton.com", "calendly.com", "notion.com",
    "segment.io", "sentry.io", "youtube.com", "ytimg.com",
    "sigstore.dev", "sigstage.dev",
    "hatch.one", "willow606.com", "exe.xyz", "multimango.com", "pariscope.dev",
    "mapbox.com", "maptiler.com", "maplibre.org", "openstreetmap.org",
    "virtualearth.net", "arcgis.com", "usda.gov",
]
# 这几个必须保留 FQDN：它们所在的父域太大（cloudflare.com 是整个 CF 官网），
# 规约过去会把无关流量也卷进来。
THIRD_EXACT = ["cdnjs.cloudflare.com"]

# 明确不采纳：要么用户连不到，要么跟 Muse 无关、代理过去只会添乱
IGNORE = {
    # Meta 内部/员工专用
    "internalfb.com": "Meta 员工专用，普通用户解析不到",
    # 证书体系：CRL/OCSP 与 Muse 无关
    "crl.comodoca.com": "CA 吊销列表，与 Muse 无关",
    "crl.globalsign.net": "CA 吊销列表，与 Muse 无关",
    "ocsp.digicert.com": "OCSP 装订检查，与 Muse 无关",
    # 证书固定自测页
    "pinningtest.appspot.com": "证书固定测试页",
    "fbpinningtest.appspot.com": "证书固定测试页",
    "insecure.pinningtest.appspot.com": "证书固定测试页",
    # 通配 DNS（测试基建）
    "nip.io": "通配 DNS 测试服务",
    "sslip.io": "通配 DNS 测试服务",
    "xip.io": "通配 DNS 测试服务",
    # Meta 家族但与 Muse 无关，单独代理没有意义
    "oculus.com": "Meta 家族但与 Muse 无关",
    "oculuscdn.com": "Meta 家族但与 Muse 无关",
    "facebook-hardware.com": "Meta 家族但与 Muse 无关",
    "facebookvirtualassistant.com": "Meta 家族但与 Muse 无关",
    "freebasics.com": "Meta 家族但与 Muse 无关",
    "internet.org": "Meta 家族但与 Muse 无关",
    "viewpointsfromfacebook.com": "Meta 家族但与 Muse 无关",
    "workplace.com": "Meta 家族但与 Muse 无关",
    "fburl.com": "Meta 短链，与 Muse 无关",
    "discoverapp.com": "Meta 家族但与 Muse 无关",
    # 系统服务：走代理反而变慢/失效
    "push.apple.com": "APNs 推送，国内可直连，代理反而拖慢",
    "icloud.com": "Apple 账号域，与 Muse 无关",
    "time.akamai.com": "NTP 校时，直连即可",
    "time.android.com": "NTP 校时，直连即可",
}


def load_repo(repo, ref, paths):
    """整仓拉取：一次 codeload 请求拿全仓库，比逐个文件问 gh api 稳得多。

    gh api 抓大文件经常 90s 超时，raw 又间歇性 reset，codeload 是实测最稳的通道。
    解包后按路径取文件；取不全就返回 None，交给逐文件通道兜底。
    """
    name = repo.split("/")[1]
    with tempfile.TemporaryDirectory() as td:
        gz = os.path.join(td, "src.tar.gz")
        url = f"https://codeload.github.com/{repo}/tar.gz/refs/heads/{ref}"
        r = subprocess.run(["curl", "-fsSL", "--max-time", "180", "-o", gz, url],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None
        subprocess.run(["tar", "-xzf", gz, "-C", td], capture_output=True)
        root = os.path.join(td, f"{name}-{ref}")
        if not os.path.isdir(root):
            return None
        out = {}
        for p in paths:
            fp = os.path.join(root, p)
            if os.path.exists(fp):
                with open(fp, errors="ignore") as f:
                    out[p] = f.read()
        return out if len(out) == len(paths) else None


def fetch(repo, path, retries=3):
    """兜底：逐文件拉取上游原文，三通道依次尝试。"""
    last = "unknown error"
    for attempt in range(1, retries + 1):
        gh = shutil.which("gh")
        if gh:
            r = subprocess.run(
                [gh, "api", f"repos/{repo}/contents/{path}?ref={REF}", "--jq", ".content"],
                capture_output=True, text=True, timeout=90,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    return base64.b64decode(r.stdout.strip()).decode("utf-8")
                except Exception:
                    pass

        url = RAW.format(repo, REF, path)
        r = subprocess.run(["curl", "-fsSL", "--max-time", "60", url],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        err = (r.stderr or r.stdout or "").strip().splitlines()
        last = err[-1][:200] if err else "curl failed"

        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            last = f"urllib: {e}"

        print(f"  ! {path} 第 {attempt}/{retries} 次抓取失败：{last}")
    raise RuntimeError(last)


def covered(domain, suffixes):
    """返回能覆盖该域名的最长后缀，无则 None。"""
    best = None
    for s in suffixes:
        if domain == s or domain.endswith("." + s):
            if best is None or len(s) > len(best):
                best = s
    return best


def extract(text):
    """从取证文本里抽出像域名的 token。"""
    out = set()
    for m in HOST_RE.finditer(text):
        d = m.group(1)
        if d.count(".") >= 1 and d.rsplit(".", 1)[1] in TLDS:
            out.add(d)
    return out


def parse_loon(text):
    """辅源是 Loon 格式，直接按类型解析。"""
    exact, suffix = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(",")]
        kind = parts[0].upper()
        if len(parts) < 2 or not parts[1]:
            continue
        if kind == "DOMAIN":
            exact.append(parts[1].lower())
        elif kind == "DOMAIN-SUFFIX":
            suffix.append(parts[1].lower())
    return exact, suffix


def build_meta_rows(meta_suffix, meta_exact):
    """主集排序输出：Muse 专用 → Meta 社交 → 隐私中继。"""
    groups = [
        ("Muse 专用（逆向取证·核心）",
         ["muse.ai", "museai.com", "meta.ai", "metaaivm.com",
          "metaaiusercontent.com", "ecto1usercontent.com"]),
        ("Meta 账号与社交基础设施",
         ["meta.com", "atmeta.com", "facebook.com", "facebook.net", "fbcdn.net",
          "fb.com", "fbsbx.com", "fbpigeon.com", "facebook-dns.com",
          "messenger.com", "threads.net", "instagram.com", "cdninstagram.com",
          "whatsapp.com", "whatsapp.net", "wa.me"]),
    ]
    rows, used = [], set()
    for title, order in groups:
        items = [d for d in order if d in meta_suffix and d not in used]
        if items:
            rows.append((title, [f"DOMAIN-SUFFIX,{d}" for d in items]))
            used.update(items)
    rest = sorted(d for d in meta_suffix if d not in used)
    if rest:
        rows.append(("其它 Meta 域", [f"DOMAIN-SUFFIX,{d}" for d in rest]))
    if meta_exact:
        rows.append(("隐私中继 / 网关端点（精确域名）",
                     [f"DOMAIN,{d}" for d in sorted(meta_exact)]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    print(f"主源：{TEARDOWN}@{REF}（{len(EVIDENCE)} 个取证文件）")
    print(f"辅源：{LOON}@{REF}/{LOON_FILE}\n")

    meta_suffix, meta_exact = set(), set()
    third_suffix, third_exact = set(), set()
    skipped = {}
    failures = []

    bundle = load_repo(TEARDOWN, REF, EVIDENCE) or {}
    if bundle:
        print("  （整仓 codeload 拉取成功）")

    for path in EVIDENCE:
        if path in bundle:
            text = bundle[path]
        else:
            try:
                text = fetch(TEARDOWN, path)
            except Exception as e:
                failures.append((path, str(e)))
                continue
        hosts = extract(text)
        print(f"  {path.split('/')[-1]:34s} 提取 {len(hosts):3d} 个 host")
        for d in hosts:
            reason = IGNORE.get(d) or IGNORE.get(covered(d, IGNORE))
            if reason:
                skipped[d] = reason
                continue
            c = covered(d, META_COLLAPSE)
            if c:
                meta_suffix.add(c)
                continue
            if covered(d, META_EXACT_PARENT):
                # 父域本身（fastly-edge.com）不是可连端点，只收子域
                if d not in META_EXACT_PARENT:
                    meta_exact.add(d)
                continue
            if d in THIRD_EXACT:
                third_exact.add(d)
                continue
            c = covered(d, THIRD_SUFFIXES)
            if c:
                third_suffix.add(c)
                continue

    if failures:
        print("\n主源抓取失败，已中止（未改动任何本地文件）：")
        for path, err in failures:
            print(f"  ✗ {path}: {err}")
        return 1

    # 辅源只作补充，失败不中止
    try:
        loon = load_repo(LOON, REF, [LOON_FILE])
        loon_text = loon[LOON_FILE] if loon else fetch(LOON, LOON_FILE)
        le, ls = parse_loon(loon_text)
        for d in ls:
            if IGNORE.get(d):
                skipped[d] = IGNORE[d]
            else:
                meta_suffix.add(d)
        for d in le:
            if IGNORE.get(d) or IGNORE.get(covered(d, IGNORE)):
                skipped[d] = IGNORE.get(d, "忽略")
            elif covered(d, META_COLLAPSE):
                continue          # 已被后缀覆盖，无需重复
            elif covered(d, META_EXACT_PARENT):
                continue          # 主集已收精确项，别再漏进第三方
            elif d in THIRD_EXACT:
                third_exact.add(d)
            elif covered(d, THIRD_SUFFIXES):
                third_suffix.add(covered(d, THIRD_SUFFIXES))
            else:
                meta_exact.add(d)
        print(f"\n  辅源补充：suffix {len(ls)} / exact {len(le)}")
    except Exception as e:
        print(f"\n  ! 辅源抓取失败，仅用主源：{e}")

    if not meta_suffix:
        print("\n主集为空，疑似上游内容异常，已中止。")
        return 1

    # 主集里的精确域若已被后缀覆盖，剔除
    meta_exact = {d for d in meta_exact if not covered(d, meta_suffix)}
    # 第三方：后缀项互相覆盖的留长的那个；精确项被后缀覆盖的剔除
    third_suffix = {d for d in third_suffix
                    if not any(o != d and d.endswith("." + o) for o in third_suffix)}
    third_exact = {d for d in third_exact if not covered(d, third_suffix)}
    third = third_suffix | third_exact

    print(f"\n主集：DOMAIN-SUFFIX {len(meta_suffix)} / DOMAIN {len(meta_exact)}")
    print(f"第三方：suffix {len(third_suffix)} / exact {len(third_exact)}")
    if skipped:
        print(f"剔除 {len(skipped)} 个（不影响 Muse 连通）：")
        for d in sorted(skipped)[:6]:
            print(f"      {d} —— {skipped[d]}")
        if len(skipped) > 6:
            print(f"      ...等 {len(skipped)} 个")

    def write(prefix, rows, note):
        n_s = sum(1 for _, rs in rows for r in rs if r.startswith("DOMAIN-SUFFIX"))
        n_e = sum(1 for _, rs in rows for r in rs if r.startswith("DOMAIN,"))
        lines = [f"# {note['title']}",
                 f"# 逆向取证源：https://github.com/{TEARDOWN} @ {REF}",
                 f"#   人工整理源：https://github.com/{LOON} @ {REF}"]
        lines += [f"# {l}" for l in note["desc"]]
        lines += [f"# 统计：DOMAIN-SUFFIX {n_s} / DOMAIN {n_e}", "", "rules:"]
        for title, rs in rows:
            lines.append(f"  # ---- {title} ----")
            lines += [f"  - {r}" for r in rs]
        with open(f"{BASE}/{prefix}-rules.yaml", "w") as f:
            f.write("\n".join(lines).rstrip() + "\n")
        with open(f"{BASE}/{prefix}-rules.list", "w") as f:
            f.write("\n".join(r for _, rs in rows for r in rs) + "\n")

    os.makedirs(BASE, exist_ok=True)
    write("meta-muse", build_meta_rows(meta_suffix, meta_exact), {
        "title": "Meta Muse AI 规则集（Meta 自有域）",
        "desc": ["静态逆向取证提取：三平台二进制字符串 + 清单文件里出现的 host",
                 "覆盖 Muse 专用域（muse.ai / meta.ai / metaaivm.com）+ Meta 账号与",
                 "社交基础设施（facebook / instagram / whatsapp / fbcdn 等）+ 隐私中继",
                 "建议指向美国节点；Muse 的地区限制判出口 IP，规则集解决不了"]})
    write("meta-muse-3p", [("第三方域（连接器 / 支付 / CDN / 渲染）",
                            [f"DOMAIN-SUFFIX,{d}" for d in sorted(third_suffix)]
                            + [f"DOMAIN,{d}" for d in sorted(third_exact)])], {
        "title": "Meta Muse 第三方域规则集（可选）",
        "desc": ["Muse 代码路径能触达的非 Meta 域：Play 服务 / Stripe 支付 / 连接器",
                 "OAuth / jsDelivr 渲染 / VM 网关白名单等",
                 "可选集：APNs、NTP、地图瓦片、CRL 等已剔除（代理过去只会变慢）",
                 "按需指向美国节点，不需要就别挂这份规则集"]})

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

    d = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                       capture_output=True, text=True).stdout.strip()
    if not d:
        print("\n上游无变化，无需提交。")
        return 0

    print("\n检测到变化：")
    print(d)
    subprocess.run(["git", "add", "-A"], cwd=REPO)
    subprocess.run(
        ["git", "commit", "-m",
         f"sync: 逆向取证源 {TEARDOWN}@{REF}\n\n"
         f"Meta 域：suffix {len(meta_suffix)} / exact {len(meta_exact)}；"
         f"第三方：{len(third)}"],
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
