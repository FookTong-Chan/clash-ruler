#!/usr/bin/env python3
"""
从 blackmatrix7/ios_rule_script 同步流媒体与游戏平台规则。

上游分类（rule/Clash/<类别>/<类别>.yaml）是 classical 格式，
带 payload 列表和 IP-CIDR，直接合并即可。

产出（rule-provider/）：
  streaming-rules.*   流媒体 + 音乐 + 直播 + 台日平台
  game-rules.*        游戏平台（Steam / 主机 / 厂商）

用法:
  python3 sync_blackmatrix7.py            # 抓取 + 合并 + 构建 + 提交 + 推送
  python3 sync_blackmatrix7.py --dry-run  # 只抓取构建，不提交不推送
  python3 sync_blackmatrix7.py --no-push  # 本地提交但不 push（CI 用）

安全策略：任一类别抓取失败、或合并后为空时直接中止，不覆盖已有文件。
"""
import argparse
import base64
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT) if os.path.basename(ROOT) == "scripts" else ROOT
BASE = os.path.join(REPO, "rule-provider")

UPSTREAM = "blackmatrix7/ios_rule_script"
REF = "master"
RAW = "https://raw.githubusercontent.com/{}/{}/{}"

# 组 -> [(上游类别, 中文名)]。中文名只用于生成注释，方便看规则集里有什么。
GROUPS = {
    "streaming": [
        ("Netflix", "奈飞"), ("Disney", "迪士尼+"), ("HBO", "HBO"),
        ("HBOAsia", "HBO Asia"), ("HBOHK", "HBO 香港"), ("HBOUSA", "HBO 美国"),
        ("PrimeVideo", "亚马逊 Prime Video"), ("Spotify", "Spotify"),
        ("TIDAL", "TIDAL"), ("Deezer", "Deezer"), ("Qobuz", "Qobuz"),
        ("Twitch", "Twitch 直播"), ("Vimeo", "Vimeo"),
        ("Dailymotion", "Dailymotion"), ("Bahamut", "巴哈姆特（台湾）"),
        ("LiTV", "LiTV（台湾）"), ("friDay", "friDay（台湾）"),
        ("AbemaTV", "AbemaTV（日本）"), ("Niconico", "Niconico（日本）"),
        ("Emby", "Emby"), ("BBC", "BBC"), ("CNN", "CNN"),
    ],
    "game": [
        ("Steam", "Steam 国际"), ("PlayStation", "PlayStation"),
        ("Xbox", "Xbox"), ("Nintendo", "任天堂"), ("EA", "EA"),
        ("Ubisoft", "育碧"), ("Blizzard", "暴雪"), ("Rockstar", "R 星"),
        ("Origin", "Origin"), ("Epic", "Epic Games"),
    ],
}

# 这些类别虽然叫国服/国内向，但规则本身是国际域，不单独剔除；
# 真正要避开的是 SteamCN（国服 Steam，走直连），所以没放进 GROUPS。
KINDS = ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR",
         "IP-CIDR6", "PROCESS-NAME")

# 上游漏掉、但实测要用的域名。每次同步自动合并，不会被上游覆盖。
EXTRA_RULES = {
    # 育碧上游只收了一条 CDN 精确域名，Ubisoft Connect 的官方域反而没有
    "game": ["DOMAIN-SUFFIX,ubi.com", "DOMAIN-SUFFIX,ubisoft.com"],
}


def fetch(path, retries=3):
    """拉取上游单文件原文，三通道依次尝试。"""
    last = "unknown error"
    for attempt in range(1, retries + 1):
        gh = shutil.which("gh")
        if gh:
            r = subprocess.run(
                [gh, "api", f"repos/{UPSTREAM}/contents/{path}?ref={REF}",
                 "--jq", ".content"],
                capture_output=True, text=True, timeout=90,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    return base64.b64decode(r.stdout.strip()).decode("utf-8")
                except Exception:
                    pass

        url = RAW.format(UPSTREAM, REF, path)
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


def parse_payload(text):
    """从上游 yaml 里取出 payload 规则，保留注释里的更新时间。"""
    rules, updated = [], ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# UPDATED:"):
            updated = s.split(":", 1)[1].strip()
        if not s.startswith("- "):
            continue
        rule = s[2:].split("#")[0].strip()
        if rule and rule.split(",")[0].upper() in KINDS:
            rules.append(rule)
    return rules, updated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    print(f"上游：{UPSTREAM}@{REF}")
    total_cat = sum(len(v) for v in GROUPS.values())
    print(f"抓取 {total_cat} 个类别（流媒体 {len(GROUPS['streaming'])} / "
          f"游戏 {len(GROUPS['game'])}）\n")

    failures, results = [], {}
    for group, cats in GROUPS.items():
        merged, seen = [], set()
        per_cat = []
        for cat, cn in cats:
            path = f"rule/Clash/{cat}/{cat}.yaml"
            try:
                text = fetch(path)
            except Exception as e:
                failures.append((path, str(e)))
                continue
            rules, updated = parse_payload(text)
            fresh = [r for r in rules if r not in seen]
            seen.update(fresh)
            if fresh:
                merged.append((cn, fresh, updated))
            per_cat.append((cat, len(rules), len(fresh)))
            print(f"  [{group:9s}] {cat:14s} {len(rules):4d} 条"
                  f"（新增 {len(fresh)}）")
        results[group] = merged

    # 合并本地补充（上游缺失、实测必需）
    for group, extra in EXTRA_RULES.items():
        if group not in results:
            continue
        seen = {r for _, rs, _ in results[group] for r in rs}
        fresh = [r for r in extra if r not in seen]
        if fresh:
            results[group].append(("本地补充", fresh, ""))
            print(f"\n  + 本地补充 [{group}]：{' / '.join(fresh)}")

    if failures:
        print("\n抓取失败，已中止（未改动任何本地文件）：")
        for path, err in failures:
            print(f"  ✗ {path}: {err}")
        return 1

    os.makedirs(BASE, exist_ok=True)
    for group, merged in results.items():
        if not merged:
            print(f"\n{group} 组合并为空，疑似上游异常，已中止。")
            return 1
        total = sum(len(r) for _, r, _ in merged)
        n_dom = sum(1 for _, rs, _ in merged for r in rs
                    if r.split(",")[0].upper() in
                    ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"))
        n_ip = total - n_dom
        print(f"\n{group}：{len(merged)} 个类别，域名 {n_dom} 条 / IP 段 {n_ip} 条")

        lines = [
            f"# {'流媒体与音乐' if group == 'streaming' else '游戏平台'}规则集",
            f"# 同步自 https://github.com/{UPSTREAM} @ {REF}",
            "#   " + " / ".join(c for c, _ in GROUPS[group]),
            f"# 统计：域名类 {n_dom} / IP 段 {n_ip}，合计 {total}",
            "# 建议指向美国/对应区节点；解锁与下载都吃流量，别用计费节点",
            "",
            "rules:",
        ]
        for cn, rules, updated in merged:
            stamp = f"（上游更新于 {updated}）" if updated else ""
            lines.append(f"  # ---- {cn}{stamp} ----")
            lines += [f"  - {r}" for r in rules]

        with open(f"{BASE}/{group}-rules.yaml", "w") as f:
            f.write("\n".join(lines).rstrip() + "\n")
        with open(f"{BASE}/{group}-rules.list", "w") as f:
            f.write("\n".join(r for _, rs, _ in merged for r in rs) + "\n")

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
         f"sync: 同步上游 {UPSTREAM}@{REF}（流媒体 + 游戏）\n\n"
         + "\n".join(
             f"{g}：" + " / ".join(f"{cn} {len(rs)}" for cn, rs, _ in m)
             for g, m in results.items())],
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
