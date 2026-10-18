#!/usr/bin/env python3
"""
生成 HKJC（香港赛马会）规则集。

域名来源：用户自己的 HKJC-v2 项目实际请求的域名
（~/Documents/HKJC-v2 与 ~/Documents/HKJC项目 代码中提取），
非公开规则仓库搬运——blackmatrix7 / Loyalsoldier / meta-rules-dat
均无 HKJC 专属规则集（GitHub 代码搜索索引过期，实际已移除）。

产出：
  rule-provider/hkjc-rules.yaml   mihomo classical yaml（推荐）
  rule-provider/hkjc-rules.list   clash 传统 list
"""
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rule-provider")

# 精确域名：项目里硬编码的入口
EXACT = [
    "bet.hkjc.com",           # 投注/赔率页面（GraphQL 被 WHITELIST_ERROR 挡，只能走浏览器）
    "racing.hkjc.com",        # 赛事信息 / racecard / 赛果
    "info.cld.hkjc.com",      # 资讯 CDN（V1 用过）
    "www.hkjc.com",           # 官网主站
]

# 域名后缀：覆盖上述主域的所有子域，以及 HKJC 其他业务线
SUFFIX = [
    "hkjc.com",               # 主域（含所有子域）
    "hkjc.com.hk",
    "hkjc.co",
    "jockeyclub.com.hk",
    "thehongkongjockeyclub.com",
]

# 域名关键词：兜底（防未知子域/新业务线）
KEYWORD = [
    "hkjc",
    "jockeyclub",
]


def main():
    os.makedirs(BASE, exist_ok=True)

    total = len(EXACT) + len(SUFFIX) + len(KEYWORD)
    lines = [
        "# HKJC 香港赛马会规则集",
        "# 域名来源：本地 HKJC-v2 / HKJC项目 代码实际请求域名",
        "# 覆盖：bet.hkjc.com（赔率）、racing.hkjc.com（赛事）、info.cld.hkjc.com、官网",
        f"# 统计：DOMAIN {len(EXACT)} / DOMAIN-SUFFIX {len(SUFFIX)} / DOMAIN-KEYWORD {len(KEYWORD)}",
        "",
        "rules:",
        "  # ---- 精确域名 ----",
    ]
    lines += [f"  - DOMAIN,{d}" for d in EXACT]
    lines += ["", "  # ---- 域名后缀 ----"]
    lines += [f"  - DOMAIN-SUFFIX,{d}" for d in SUFFIX]
    lines += ["", "  # ---- 域名关键词（兜底） ----"]
    lines += [f"  - DOMAIN-KEYWORD,{k}" for k in KEYWORD]

    with open(f"{BASE}/hkjc-rules.yaml", "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    plain = (
        [f"DOMAIN,{d}" for d in EXACT]
        + [f"DOMAIN-SUFFIX,{d}" for d in SUFFIX]
        + [f"DOMAIN-KEYWORD,{k}" for k in KEYWORD]
    )
    with open(f"{BASE}/hkjc-rules.list", "w") as f:
        f.write("\n".join(plain) + "\n")

    print(f"DOMAIN         {len(EXACT)}")
    print(f"DOMAIN-SUFFIX  {len(SUFFIX)}")
    print(f"DOMAIN-KEYWORD {len(KEYWORD)}")
    print(f"总计           {total}")
    print(f"输出           {BASE}/hkjc-rules.yaml")
    print(f"               {BASE}/hkjc-rules.list")


if __name__ == "__main__":
    main()
