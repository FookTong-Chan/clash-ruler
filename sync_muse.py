#!/usr/bin/env python3
"""
从 juner922/muse-loon-rules 抓取 Meta Muse AI 规则 → 转成 mihomo 规则集 → 重建 mrs。

上游是 Loon 规则格式（DOMAIN-SUFFIX,xxx 不带策略名），与 mihomo 的
classical 列表格式一致，只需规范化大小写 + 去重即可。

产出（rule-provider/）：
  meta-muse-rules.yaml    推荐用这个（classical，一条 RULE-SET 全包）
  meta-muse-rules.list    clash 传统格式
  meta-muse-domains.mrs   mrs 版（只有域名，本规则集不含 IP 段）

用法:
  python3 sync_muse.py            # 抓取 + 构建 + 提交 + 推送
  python3 sync_muse.py --dry-run  # 只抓取构建，不提交不推送
  python3 sync_muse.py --no-push  # 本地提交但不 push（GitHub Actions 用）

安全策略：抓取失败、或解析出 0 条规则时直接中止，不覆盖已有文件。
"""
import argparse
import base64
import os
import shutil
import subprocess
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT) if os.path.basename(ROOT) == "scripts" else ROOT
BASE = os.path.join(REPO, "rule-provider")

UPSTREAM = "juner922/muse-loon-rules"
REF = "main"
SOURCE = "MuseAI.list"

RAW = "https://raw.githubusercontent.com/{}/{}/{}"
PREFIX = "meta-muse"

# 上游漏掉、但 Muse / Meta 生态实测需要的域名。每次同步自动合并。
EXTRA_RULES = {
    # Muse 可运行在 WhatsApp / Messenger 内，threads 同属 Meta 社交基础设施
    "suffix": ["messenger.com", "threads.net"],
}

KINDS = ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR")


def fetch(name, retries=3, timeout=90):
    """拉取上游单个文件原文。

    三条通道依次尝试，任一成功即返回：
      1. gh api    —— 本地已认证时最快、最稳
      2. curl      —— CI 环境（raw 直连不被墙）
      3. urllib    —— 最后兜底
    """
    last = "unknown error"
    for attempt in range(1, retries + 1):
        gh = shutil.which("gh")
        if gh:
            r = subprocess.run(
                [gh, "api", f"repos/{UPSTREAM}/contents/{name}?ref={REF}",
                 "--jq", ".content"],
                capture_output=True, text=True, timeout=timeout,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    return base64.b64decode(r.stdout.strip()).decode("utf-8")
                except Exception:
                    pass

        r = subprocess.run(
            ["curl", "-fsSL", "--max-time", "60", RAW.format(UPSTREAM, REF, name)],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        err = (r.stderr or r.stdout or "").strip().splitlines()
        last = err[-1][:200] if err else "curl failed"

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
    """解析上游规则，保留分组注释，返回 [(分组标题, 规则串)]。"""
    rows = []
    group = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            # 形如 `# === 核心: Muse 应用域名 ===` 的分组标题
            body = s.lstrip("#").strip()
            if body.startswith("===") and body.endswith("==="):
                group = body.strip("=").strip()
            continue
        parts = [p.strip() for p in s.split(",")]
        kind = parts[0].upper()
        if kind not in KINDS or len(parts) < 2 or not parts[1]:
            continue
        # Loon 允许尾随策略名（DOMAIN-SUFFIX,muse.ai,Proxy），只取前两段
        rows.append((group, f"{kind},{parts[1].lower()}"))
    return rows


def clean(rows, extra):
    """去重并合并本地补充，保持上游原顺序。"""
    for kind, items in extra.items():
        for d in items:
            rows.append(("本地补充", f"DOMAIN-{kind.upper()},{d.lower()}"))

    seen = set()
    out = []
    for group, rule in rows:
        if rule in seen:
            continue
        seen.add(rule)
        out.append((group, rule))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="不提交不推送")
    ap.add_argument("--no-push", action="store_true",
                    help="提交但不 push（GitHub Actions 用）")
    args = ap.parse_args()

    print(f"上游：{UPSTREAM}@{REF}/{SOURCE}\n")

    try:
        text = fetch(SOURCE)
    except Exception as e:
        print(f"抓取失败，已中止（未改动任何本地文件）：{e}")
        return 1

    rows = clean(parse(text), EXTRA_RULES)
    if not rows:
        print("解析结果为空，疑似上游内容异常，已中止。")
        return 1

    # 按分组聚合，组内的原始顺序保留
    groups = OrderedDict()
    for group, rule in rows:
        groups.setdefault(group or "其它", []).append(rule)

    counts = {}
    for _, rule in rows:
        k = rule.split(",")[0]
        counts[k] = counts.get(k, 0) + 1
    print("抓取结果：" + " / ".join(f"{k} {v}" for k, v in counts.items()))

    lines = [
        "# Meta Muse AI 规则集",
        f"# 同步自 https://github.com/{UPSTREAM} @ {REF}",
        f"#   {SOURCE}",
        "# 覆盖：muse.ai / metaaivm.com（Muse 专用）+ Meta 账号与社交基础设施",
        "#   （facebook / instagram / whatsapp / fbcdn / meta.com 等）",
        "# 建议指向美国节点；Muse 有地区限制，出口 IP 需美区原生/家宽",
        "# 统计：" + " / ".join(f"{k} {v}" for k, v in counts.items()),
        "",
        "rules:",
    ]
    for group, rules in groups.items():
        lines.append(f"  # ---- {group} ----")
        lines += [f"  - {r}" for r in rules]

    os.makedirs(BASE, exist_ok=True)
    with open(f"{BASE}/{PREFIX}-rules.yaml", "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    with open(f"{BASE}/{PREFIX}-rules.list", "w") as f:
        f.write("\n".join(r for _, r in rows) + "\n")

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
         f"sync: 同步上游 {UPSTREAM}@{REF}\n\n"
         + " / ".join(f"{k} {v}" for k, v in counts.items())],
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
