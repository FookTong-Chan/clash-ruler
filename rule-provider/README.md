# 金融规则集（Finance Rule Set）

从 [koo17173/rule-set](https://github.com/koo17173/rule-set) 提取全部金融相关规则，去重合并后转换为 mihomo 原生 `.mrs` 二进制格式。

## 覆盖范围

| 类别 | 机构 | 域名规则 |
|---|---|---|
| **港美股券商** | 富途牛牛 / moomoo | 45 条 |
| | 长桥 Longbridge | 16 条 |
| | 老虎证券 Tiger | 13 条 |
| | 雪球 Snowball X | 8 条 |
| | 盈透 Interactive Brokers | 2 条 |
| | 嘉信理财 Schwab | 4 条 |
| **A股券商/资讯** | 同花顺（含问财、iFinD、51基金） | 31 条 |
| | 东方财富（含股吧、财富通） | 34 条 |
| | 华泰证券（含涨乐财富通） | 10 条 |

另含富途/moomoo 的 8 条 `DOMAIN-KEYWORD` 兜底规则，以及 69 个券商行情/交易服务器 IP 段。

## 文件

```
rule-provider/
├── finance-domains.mrs    3.1 KB   202 条域名规则（binary, magic 28b52ffd）
├── finance-ipcidr.mrs      454 B     69 条 IP 段规则（binary）
├── finance-rules.yaml      10 KB     合并后的完整 YAML（人工查阅/编辑用）
├── finance-rules.list      8.6 KB    合并后的完整 list（导入 Sub-Store 等用）
├── finance-domains.yaml    6.4 KB    拆分后的域名部分
└── finance-ipcidr.yaml     3.5 KB    拆分后的 IP 部分
```

## 为什么是两个 mrs 而不是一个

mrs 的文件头里**行为类型（domain / ipcidr）是单值编码的**，一个文件不可能同时装两种规则。
所以金融规则集拆成：

- `finance-domains.mrs` → behavior: domain
- `finance-ipcidr.mrs` → behavior: ipcidr

两者在配置里分别引用即可。

## 用法

把两个 `.mrs` 放进 OpenClash / mihomo 的 `rule-provider` 目录，在配置里引用：

```yaml
rule-providers:
  finance-domain:
    type: file
    behavior: domain
    format: mrs
    path: ./rule-provider/finance-domains.mrs
  finance-ipcidr:
    type: file
    behavior: ipcidr
    format: mrs
    path: ./rule-provider/finance-ipcidr.mrs

rules:
  # 精确指定：放在其他规则之前，优先级更高
  - RULE-SET,finance-domain,香港节点
  - RULE-SET,finance-ipcidr,香港节点,no-resolve
```

> 注意 `type: file` 而不是 `type: mrs`——mrs 是 `format` 的取值，`type` 指数据来源（file/http/inline）。

## 重新生成

```bash
python3 build_mrs.py            # 输出到 rule-provider/
python3 build_mrs.py /some/dir  # 指定输出目录
```

脚本会做三件事：读 `finance-rules.list` → `ipaddress.collapse_addresses()` 合并冗余网段 → 调用 mihomo 转成 mrs。

**不需要预装 mihomo** —— 脚本按当前平台自动下载对应架构的内核到项目根目录（已 gitignore）。查找顺序：`MIHOMO_PATH` 环境变量 → `./mihomo` → PATH → 自动下载。

上游规则更新后，重新跑 `scripts/merge_finance.py` 覆盖 `finance-rules.list`，再跑一次 `build_mrs.py` 即可。

## 数据来源与取舍

**源文件**：`BrokerHK`、`HK_Broker.conf`、`BrokerCN`、`BrokerHT`、`Stocks.list`、`StocksHK.list`

**已排除**：`Others.list`（nodeseek 等资讯站）、`Talkatone&T-mobile.list`、`UKMobile.list`（号码段服务）

**合并时的处理**：

1. 六个文件内容大量重叠（如富途域名在 4 个文件里重复），取并集去重。
2. 精确 `DOMAIN` 规则排在 `DOMAIN-SUFFIX` 之前，避免被宽泛后缀抢先匹配。
3. 剔除了两个过宽的裸 TLD 后缀 `18.cn`、`18.com.cn`——它们是东方财富的短域名，但作为后缀会误伤所有 `*.18.cn` 的无关站点。
4. IP 段用 `collapse_addresses()` 归并：89 条输入去冗余 20 条（如 `101.32.198.0/24` 被 `101.32.0.0/16` 覆盖），这是无损的。