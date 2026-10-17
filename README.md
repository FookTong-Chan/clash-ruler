# 金融规则集（Finance Rule Set）

从 [koo17173/rule-set](https://github.com/koo17173/rule-set) 实时同步金融规则，**按机构归属拆分为内地 / 香港两组**，转换为 mihomo 原生 `.mrs` 二进制格式。

## 拆分逻辑

| 组 | 机构 | 建议策略 |
|---|---|---|
| **cn-finance** | 同花顺、东方财富、华泰（内地） | `DIRECT` 直连 |
| **hk-finance** | 富途·moomoo、长桥、老虎、雪球、盈透、Schwab、华泰HK | 代理节点 |

这样内地券商App（同花顺、涨乐财富通、东方财富）走直链保速度，港美股券商走代理保连通。

## 文件

```
rule-provider/
├── cn-finance-domains.mrs   1.2 KB   75 条域名规则
├── cn-finance-ipcidr.mrs    141 B    16 条 IP 段
├── cn-finance-rules.yaml    3.3 KB   内地组源规则（查阅/编辑）
├── cn-finance-rules.list    2.5 KB   内地组源规则
├── hk-finance-domains.mrs   2.1 KB  128 条域名规则
├── hk-finance-ipcidr.mrs    361 B    53 条 IP 段
├── hk-finance-rules.yaml    6.6 KB   香港组源规则
└── hk-finance-rules.list    5.4 KB   香港组源规则
```

## 用法

```yaml
rule-providers:
  cn-domain:  {type: file, behavior: domain, format: mrs, path: ./rule-provider/cn-finance-domains.mrs}
  cn-ipcidr:  {type: file, behavior: ipcidr, format: mrs, path: ./rule-provider/cn-finance-ipcidr.mrs}
  hk-domain:  {type: file, behavior: domain, format: mrs, path: ./rule-provider/hk-finance-domains.mrs}
  hk-ipcidr:  {type: file, behavior: ipcidr, format: mrs, path: ./rule-provider/hk-finance-ipcidr.mrs}

rules:
  # 内地券商 → 直连
  - RULE-SET,cn-domain,DIRECT
  - RULE-SET,cn-ipcidr,DIRECT,no-resolve
  # 香港/海外券商 → 代理
  - RULE-SET,hk-domain,香港券商
  - RULE-SET,hk-ipcidr,香港券商,no-resolve
  - MATCH,DIRECT
```

> 注意 `type: file` + `format: mrs`，不是 `type: mrs`。
> 策略组名不要和代理节点同名，否则内核报 `loop is detected in ProxyGroup`。

## 自动同步上游

```bash
python3 sync_from_upstream.py            # 抓取 + 归类 + 构建 + 推送
python3 sync_from_upstream.py --dry-run  # 只抓取归类，不推送
```

每次运行从 `koo17173/rule-set@main` 拉取 6 个金融文件，按机构归类后重建全部 mrs，**仅在内容有变化时**才 commit + push。抓取失败或某组为空时直接中止，不会用空规则集覆盖已有内容。

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
