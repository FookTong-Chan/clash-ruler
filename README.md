# 分流规则集（Clash Rule）

两套 mihomo 原生 `.mrs` / `.yaml` 规则集，每 12 小时自动同步上游：

| 规则集 | 来源 | 建议策略 |
|---|---|---|
| **cn-finance** | [koo17173/rule-set](https://github.com/koo17173/rule-set) 按机构拆分 | `DIRECT` 直连 |
| **hk-finance** | 同上 | 代理节点 |
| **meta-muse** | [juner922/muse-loon-rules](https://github.com/juner922/muse-loon-rules) | 美国节点 |

## 金融规则拆分逻辑

| 组 | 机构 | 建议策略 |
|---|---|---|
| **cn-finance** | 同花顺、东方财富、华泰（内地） | `DIRECT` 直连 |
| **hk-finance** | 富途·moomoo、长桥、老虎、雪球、盈透、Schwab、华泰HK | 代理节点 |

这样内地券商App（同花顺、涨乐财富通、东方财富）走直链保速度，港美股券商走代理保连通。

## Meta Muse 规则

`MuseAI.list` 是 Loon 格式（`DOMAIN-SUFFIX,xxx` 不带策略名），与 mihomo 的 classical 列表一致，转换时只做小写化与去重。内容分两部分：

- **Muse 专用**：`muse.ai` / `museai.com` / `metaaivm.com` / `metaaiusercontent.com` / `ecto1usercontent.com`，以及 6 个精确域名（OHTTP 中继、隐私网关等 Cloudflare/Fastly 端点）
- **Meta 账号与社交基础设施**：`meta.com` / `facebook.com` / `instagram.com` / `whatsapp.com` / `fbcdn.net` / `fbsbx.com` 等

本地另补了 `messenger.com`、`threads.net`（Muse 可在 WhatsApp / Messenger 内运行，threads 同属 Meta 社交域）。

> **Muse 有地区限制**：域名全走代理也可能提示"尚未在你的国家或地区开放"——那是出口 IP 判定，机房 IP、广播 IP 会被拦，需要美区原生/家宽节点。规则集只能保证域名走对，保证不了地区。

## 文件

```
rule-provider/
├── cn-finance-rules.yaml    3.3 KB   内地券商（推荐用这个）
├── cn-finance-rules.list    2.5 KB   内地组规则（clash 传统格式）
├── cn-finance-domains.mrs   672 B    内地组域名 mrs
├── cn-finance-ipcidr.mrs    141 B    内地组 IP 段 mrs
├── hk-finance-rules.yaml    6.6 KB   港外券商（推荐用这个）
├── hk-finance-rules.list    5.4 KB   香港组规则
├── hk-finance-domains.mrs   1.1 KB   香港组域名 mrs
├── hk-finance-ipcidr.mrs    361 B    香港组 IP 段 mrs
├── meta-muse-rules.yaml     1.5 KB   Meta Muse AI（推荐用这个）
├── meta-muse-rules.list     763 B    Meta Muse AI 规则
└── meta-muse-domains.mrs    353 B    Meta Muse AI 域名 mrs
```

> `meta-muse` 只有域名、不含 IP 段，所以没有对应的 `-ipcidr.mrs`——构建脚本会跳过空类型，不会产出 0 条目的空壳文件。

## 用法

### 方式一：yaml + classical（推荐）

一条规则集搞定，`DOMAIN-KEYWORD` 兜底规则也能用：

```yaml
rule-providers:
  🇨🇳 国内券商: {<<: *Classicals, url: "https://raw.githubusercontent.com/FookTong-Chan/clash-ruler/main/rule-provider/cn-finance-rules.yaml"}
  🇭🇰 香港券商: {<<: *Classicals, url: "https://raw.githubusercontent.com/FookTong-Chan/clash-ruler/main/rule-provider/hk-finance-rules.yaml"}
  🤖 Meta Muse: {<<: *Classicals, url: "https://raw.githubusercontent.com/FookTong-Chan/clash-ruler/main/rule-provider/meta-muse-rules.yaml"}

rules:
  - RULE-SET,🇨🇳 国内券商,国内券商      # DIRECT
  - RULE-SET,🇭🇰 香港券商,香港券商      # 代理
  - RULE-SET,🤖 Meta Muse,美国节点      # 需在 AD / GeoCN / MATCH 之前
```

### 方式二：mrs（体积小，但装不下关键词规则）

mrs 的 `behavior` 是单值编码，domain 和 ipcidr 必须分文件，所以是 4 个：

```yaml
domainMRS: &domainMRS {type: http, format: mrs, behavior: domain, interval: 28800}
ipcidr:    &IPmrs     {type: http, format: mrs, behavior: ipcidr, interval: 28800}

rule-providers:
  cn-domain: {<<: *domainMRS, url: ".../cn-finance-domains.mrs"}
  cn-ipcidr: {<<: *IPmrs,     url: ".../cn-finance-ipcidr.mrs"}
  hk-domain: {<<: *domainMRS, url: ".../hk-finance-domains.mrs"}
  hk-ipcidr: {<<: *IPmrs,     url: ".../hk-finance-ipcidr.mrs"}
  muse:      {<<: *domainMRS, url: ".../meta-muse-domains.mrs"}

rules:
  - RULE-SET,cn-domain,DIRECT
  - RULE-SET,cn-ipcidr,DIRECT,no-resolve
  - RULE-SET,hk-domain,香港券商
  - RULE-SET,hk-ipcidr,香港券商,no-resolve
  - RULE-SET,muse,美国节点
```

> **`format: yaml` 必须配 `behavior: classical`**。配成 `behavior: domain` 时，
> `DOMAIN-SUFFIX,xxx` 这类带类型的行会被当作字面域名，结果是 ruleCount 正常
> 但一条都匹配不上——这个组合是无效的，别用。

> 策略组名不要和代理节点同名，否则内核报 `loop is detected in ProxyGroup`。

> 规则要放在 GeoCN / ChinaDirect / MATCH 兜底**之前**：香港券商域名不在
> ChinaMax 里，被 MATCH 接走会错走全球备用。

## 自动同步上游

```bash
python3 sync_from_upstream.py            # 金融：抓取 + 归类 + 构建 + 推送
python3 sync_muse.py                     # Meta Muse：抓取 + 构建 + 推送
# 两者都支持 --dry-run / --no-push
```

`sync_from_upstream.py` 每次从 `koo17173/rule-set@main` 拉取 6 个金融文件，按机构归类后重建全部 mrs；`sync_muse.py` 从 `juner922/muse-loon-rules@main` 拉取 `MuseAI.list`。两者都**仅在内容有变化时**才 commit + push，抓取失败或解析为空时直接中止，不会用空规则集覆盖已有内容。

**不需要预装 mihomo** —— 脚本按平台自动下载内核到项目根目录（已 gitignore）。

## 归类规则

分类靠域名特征识别（`sync_from_upstream.py` 的 `ENTITY_PATTERNS`），不依赖上游文件的注释结构。两条特殊处理：

- **内地券商的 `.hk` 子公司统一走代理**：`htsc.com.hk`（华泰金控香港）、`emsec.hk`（东方财富国际证券香港）都归香港组；其余华泰、东方财富域名归内地组。规则是「`.hk` 子公司走代理，内地主体走直连」。
- **IP 段按网段归属**：江苏电信/联通/移动、广东阿里云、上海华为云、同花顺的 `122.9.0.0/16`、`221.236.0.0/16` 算内地；其余一律算香港/海外。

上游每次新增域名若无法识别归属，脚本会打印告警并剔除，不会静默丢弃——看到告警就往 `ENTITY_PATTERNS` 里补一条模式。

## 自动更新（两层）

规则集的变化要经过两层才能到你的路由器：

```
上游 koo17173/rule-set ──①──> 你的 GitHub 仓库 ──②──> 路由器 OpenClash
      （规则变化源）        本仓库的 .mrs 文件        rule-provider 拉取
```

**① GitHub 自己更新** —— 由 `.github/workflows/sync-rules.yml` 完成，跑在 GitHub 服务器上，**不依赖你本机开机或网络**：

- 频率：**每 12 小时**一次（UTC 00:00 / 12:00，即北京时间 08:00 / 20:00）
- 想改成 24 小时：把工作流里的 `- cron: "0 */12 * * *"` 改成 `- cron: "0 0 * * *"`
- 也可在 GitHub 网页 **Actions → 同步金融规则集 → Run workflow** 手动触发
- 上游无变化时**不会**制造空提交

**② 路由器拉取** —— 在 OpenClash 的 rule-provider 里配 `interval`，mihomo 会按时重新下载：

```yaml
cn-domain:
  type: http
  behavior: domain
  format: mrs
  url: https://raw.githubusercontent.com/FookTong-Chan/clash-ruler/main/rule-provider/cn-finance-domains.mrs
  interval: 43200        # 12 小时（秒）；86400 即 24 小时
```

> raw.githubusercontent.com 只是静态文件托管，它自己不会变——必须靠 ① 推送新版本，② 才能拉到。

本地手动同步（一般不需要， Actions 会自动做）：

```bash
python3 sync_from_upstream.py            # 抓取 + 归类 + 构建 + 提交 + 推送
python3 sync_from_upstream.py --dry-run  # 只抓取归类，不提交
```

## 数据来源

**纳入**：`BrokerHK`、`HK_Broker.conf`、`BrokerCN`、`BrokerHT`、`Stocks.list`、`StocksHK.list`

**排除**：`Others.list`（nodeseek 等资讯站）、`Talkatone&T-mobile.list`、`UKMobile.list`（号码段服务）

**合并时的处理**：

1. 六个文件内容大量重叠（富途域名在 4 个文件里重复），取并集去重。
2. 精确 `DOMAIN` 规则排在 `DOMAIN-SUFFIX` 之前，避免被宽泛后缀抢先匹配。
3. 剔除两个过宽的裸 TLD 后缀 `18.cn`、`18.com.cn`——它们是东方财富的短域名，但作为后缀会误伤所有 `*.18.cn` 的无关站点。
4. IP 段用 `collapse_addresses()` 归并去冗余。
