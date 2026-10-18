# 分流规则集（Clash Rule）

两套 mihomo 原生 `.mrs` / `.yaml` 规则集，每 12 小时自动同步上游：

| 规则集 | 来源 | 建议策略 |
|---|---|---|
| **cn-finance** | [koo17173/rule-set](https://github.com/koo17173/rule-set) 按机构拆分 | `DIRECT` 直连 |
| **hk-finance** | 同上 | 代理节点 |
| **meta-muse** | [mahdi-salmanzade/meta-muse-teardown](https://github.com/mahdi-salmanzade/meta-muse-teardown) 二进制逆向取证 | 美国节点 |
| **wifi-calling** | 社区实测整理（无统一上游，本地维护） | 号码归属国节点 |

## 金融规则拆分逻辑

| 组 | 机构 | 建议策略 |
|---|---|---|
| **cn-finance** | 同花顺、东方财富、华泰（内地） | `DIRECT` 直连 |
| **hk-finance** | 富途·moomoo、长桥、老虎、雪球、盈透、Schwab、华泰HK | 代理节点 |

这样内地券商App（同花顺、涨乐财富通、东方财富）走直链保速度，港美股券商走代理保连通。

## Meta Muse 规则

主源是 [mahdi-salmanzade/meta-muse-teardown](https://github.com/mahdi-salmanzade/meta-muse-teardown) 的**二进制逆向取证**：从 macOS / iOS / Android 三份样本的 `16-network-*.txt` 里正则提取静态分析出的 host，再按角色归类。二手整理源 [juner922/muse-loon-rules](https://github.com/juner922/muse-loon-rules) 只用来补前者的文本里没直接出现的裸域（`atmeta.com` / `fb.com` / `whatsapp.net` 等）。

**主集 `meta-muse`（Meta 自有域，建议美国节点）**

- **Muse 专用**：`muse.ai` / `museai.com` / `meta.ai` / `metaaivm.com` / `metaaiusercontent.com` / `ecto1usercontent.com`
  取证里出现的实际端点：`agent.meta.ai`、`api.meta.ai`、`hatch-api.meta.ai`（REST "Stefi"）、`rupload.meta.ai`、`hatch.metaaivm.com`（VM 网关 WSS `/v1/noise`）、`shortwave.facebook.com`（语音 ASR）。
- **Meta 账号与社交基础设施**：`meta.com` / `facebook.com` / `facebook.net` / `fbcdn.net` / `fb.com` / `fbsbx.com` / `fbpigeon.com` / `facebook-dns.com` / `messenger.com` / `threads.net` / `instagram.com` / `whatsapp.com` / `whatsapp.net` / `wa.me`
- **隐私中继（精确域名）**：`meta-ohttp-{relay,config}-prod.fastly-edge.com`、`meta-ohttp-relay-dev.fastly-edge.com`、`meta.privacy-gateway.cloudflare.com`、`meta.hpke-keys.privacy-gateway.cloudflare.com`、`hatch.ecto1.ai`

**可选集 `meta-muse-3p`（第三方域）**

Muse 代码路径能触达的非 Meta 域：Play 服务与 FCM（Android 必需）、Stripe 支付、连接器 OAuth（Spotify / Peloton / HealthEx / Notion / Calendly）、渲染 CDN（jsDelivr / cdnjs / unpkg）、VM 网关白名单（`hatch.one` / `willow606.com` / `exe.xyz` / `multimango.com` / `pariscope.dev`）、Sigstore 信任根。

**默认不挂载它**——这些域跟你现有的分流容易打架（比如 `google.com` 会把 Google 全家卷进去）。需要哪个单独抄一条就行。

**明确剔除的**（代理过去只会添乱，脚本里写了剔除理由）：APNs 推送（`push.apple.com`，国内可直连）、NTP 校时（`time.akamai.com` / `time.android.com`）、CA 的 CRL/OCSP、证书固定自测页、通配 DNS 测试域（`nip.io` 一类）、Meta 家族里与 Muse 无关的品牌域（Oculus / Workplace / Internet.org / freebasics 等）、员工专用的 `internalfb.com`。

> **Muse 有地区限制**：域名全走代理也可能提示"尚未在你的国家或地区开放"——那是出口 IP 判定，机房 IP、广播 IP 会被拦，需要美区原生/家宽节点。规则集只能保证域名走对，保证不了地区。

## WiFi Calling 规则

海外 eSIM / 实体卡（giffgaff、Vodafone UK、CMLinkUK、香港 CSL、美国 T-Mobile）在国内漫游时，靠 WiFi Calling 保号、接本地来电。ePDG 是运营商侧的 IMS 网关，它的流量必须走**号码归属国**的节点，否则 IMS 注册不上、开关打不开。

| 运营商 | 归属 | 覆盖条目 |
|---|---|---|
| **全球 ePDG 兜底** | 所有国家 | `DOMAIN-SUFFIX,pub.3gppnetwork.org` |
| **英国 O2 UK / giffgaff** | 英国 | `epdg.epc.mnc010.mcc234.pub.3gppnetwork.org`、`87.194.0.0/16` |
| **英国 Vodafone UK** | 英国 | `mnc015` 系列 + `entsrv-uk.vodafone.com` + `vuk-gto.prod.ondemandconnectivity.com` + `88.82.0.0/19` |
| **英国 CMLinkUK（EE）** | 英国 | `46.68.0.0/17` |
| **香港 CSL** | 中国香港 | `mnc000.mcc454` 系列 |
| **美国 T-Mobile** | 美国 | `mnc240/mnc260` 系列 + `t-mobile.com` + 三个 IP 段 |
| **Apple 地区检测** | — | `gspe1-ssl.ls.apple.com` |

`pub.3gppnetwork.org` 那条后缀是关键：ePDG 的域名是 3GPP 标准命名（`epdg.epc.mncXXX.mccYYY.pub.3gppnetwork.org`），一条就覆盖了已列出和没列出的所有运营商，包括你以后新办的其他国家 eSIM。

**三个坑，不解决一定失败**：

1. **UDP**：ePDG 走 IKE（UDP 500）+ IPsec NAT-T（UDP 4500），节点不支持 UDP 就废了。部分机场和中转会禁 UDP。
2. **fake-ip-filter 必须加** `+.pub.3gppnetwork.org`。ePDG 域名是系统层（IPSec 客户端）解析的，不经过应用层代理；fake-ip 模式下它拿到的是 `198.18.x.x` 假 IP，域名规则一条都匹配不上。这条是 linux.do 上实测出来的结论，最难排查。
3. **设备**：iOS 需要运营商版本 ≥ 58.0 或 iOS 17.4+。国产安卓（一加 / OPPO / 小米，实测配了 Shizuku + Pixel IMS 也不行）的 IMS 普遍拉不起，建议用 iPhone。

**拉起流程**：关 WiFi 和 WiFi Calling 开关 → 开飞行模式 → 关掉国内 SIM → 连上代理 → 打开 giffgaff 的 WiFi Calling 开关 → 运营商名变成 giffgaff 即成功，之后可以恢复。

OpenClash 配法：

```yaml
# 1. DNS 设置 → Fake-IP-Filter 里加这一行（必须）
fake-ip-filter:
  - "+.pub.3gppnetwork.org"

rule-providers:
  📞 WiFi Calling: {<<: *Classicals, url: "https://cdn.jsdelivr.net/gh/FookTong-Chan/clash-ruler@main/rule-provider/wifi-calling-rules.yaml"}

rules:
  # 放在 GeoCN / MATCH 之前，指向英国（或号码归属国）节点
  - RULE-SET,📞 WiFi Calling,🇬🇧 英国
```

条目来源均为实测而非猜测：路由器 tcpdump + Wireshark 抓包（cxorz.com）、白菜博客、linux.do 讨论、[bunizao/TutuBetterRules](https://github.com/bunizao/TutuBetterRules) 的 CSL / T-Mobile 地区列表。这份规则集没有统一上游，是本地维护的，不在自动同步范围内。

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
├── meta-muse-rules.yaml     1.7 KB   Meta Muse AI（推荐用这个）
├── meta-muse-rules.list     900 B    Meta Muse AI 规则
├── meta-muse-domains.mrs    383 B    Meta Muse AI 域名 mrs
├── meta-muse-3p-rules.yaml  1.5 KB   Muse 第三方域（可选，默认不挂）
├── meta-muse-3p-rules.list  800 B    Muse 第三方域规则
├── meta-muse-3p-domains.mrs 427 B    Muse 第三方域 mrs
├── wifi-calling-rules.yaml  2.3 KB   WiFi Calling（推荐用这个）
├── wifi-calling-rules.list  850 B    WiFi Calling 规则
├── wifi-calling-domains.mrs 256 B    WiFi Calling 域名 mrs
└── wifi-calling-ipcidr.mrs  106 B    WiFi Calling IP 段 mrs
```

> Muse 两组都只有域名、不含 IP 段，所以没有对应的 `-ipcidr.mrs`——构建脚本会跳过空类型，不会产出 0 条目的空壳文件。

## 用法

### 国内拉不动 raw 时，换 jsDelivr

把链接里的 `https://raw.githubusercontent.com/FookTong-Chan/clash-ruler/main/` 整段替换成
`https://cdn.jsdelivr.net/gh/FookTong-Chan/clash-ruler@main/` 即可，其余路径不变：

```
https://cdn.jsdelivr.net/gh/FookTong-Chan/clash-ruler@main/rule-provider/meta-muse-rules.yaml
```

`.mrs` 同样适用。路由器在国内直连 raw 常超时/被reset，建议直接用 CDN 版本。

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
python3 sync_teardown.py                 # Meta Muse：抓取 + 归类 + 构建 + 推送
# 两者都支持 --dry-run / --no-push
```

`sync_from_upstream.py` 每次从 `koo17173/rule-set@main` 拉取 6 个金融文件，按机构归类后重建全部 mrs；`sync_teardown.py` 整仓 codeload 拉取逆向取证源，提取 4 个 `16-network-*.txt` 里的 host 后归类。两者都**仅在内容有变化时**才 commit + push，抓取失败或结果为空时直接中止，不会用空规则集覆盖已有内容。

Muse 脚本的三条经验：

- 从自由文本里抠域名，光靠形状正则会收进一堆文件名（`01-authenticity.txt`）和 RPC 方法名（`activity.log`）——必须卡 TLD 白名单。
- 归类表要留"明确剔除 + 剔除理由"，剔除项单独打印。取证文本里 APNs、NTP、CRL、测试域都跟 Muse 沾边，全收进去规则集就废了。
- 父域规约要看宽窄：`accounts.google.com → google.com` 合理，`cdnjs.cloudflare.com → cloudflare.com` 就把 CF 官网整个卷进来了。

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
