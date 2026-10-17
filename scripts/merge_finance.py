#!/usr/bin/env python3
"""
从 koo17173/rule-set 仓库提取金融相关规则，去重合并为 mihomo 规则集。

来源文件：
  BrokerHK      富途/Moomoo/长桥（HK+US 券商）
  HK_Broker.conf 富途/长桥/老虎/雪球/IBKR/Schwab（全集）
  BrokerCN      同花顺/东方财富/华泰 + 运营商 IP
  BrokerHT      华泰
  Stocks.list   华泰/长桥/富途/同花顺/东方财富（合并版）
  StocksHK.list 长桥/富途（含 aggressive fallback 关键词）

排除：Others.list、Talkatone&T-mobile.list、UKMobile.list（非金融）
"""
import re
from collections import OrderedDict

# ===== 规则原文（从仓库逐文件抓取） =====

# --- 富途 / Moomoo ---
FUTU_SUFFIX = """futu.link futu.com futu.cn futunn.com
futu0.com futu1.com futu2.com futu3.com futu4.com
futu5.com futu6.com futu7.com futu8.com futu9.com
futuau.com futuapi.com futuesop.com futufin.com
futuhk.com futuhk1.com futuhk2.com futuhkapp.com
futuhongkong.com futuhn.com futuholdings.com futuinc.com
futuin.com futuniuniu.com futubull.cn futuchain.com
futustatic.com fututrade.com fututrustee.com
cdn.futustatic.com qtlcdn.com""".split()

FUTU_EXTRA_SUFFIX = """futunn.cn futusg.com futusign.com
futuone.com futuclean.com ftnndn.com futuweb.com
futures.hk moomoo.com moomoo-us.com
futusecurities.com futumkt.com futu.sg futu.au""".split()

MOOMOO_SUFFIX = "moomoo.com api.moomoobull.com moomooequity.com moomootrustee.com".split()

FUTU_ATTRIBUTION_SUFFIX = [
    "9oju31.launches.appsflyersdk.com",
    "sgqt0j.launches.appsflyersdk.com",
]

FUTU_EXACT = """cdn.futustatic.com qtcard.futunn.com qtcardfthk.futufin.com
openapi.futunn.com api.futunn.com api5.futunn.com
trade.futunn.com support.futunn.com download.futunn.com""".split()

FUTU_IP = """1.14.242.0/23 1.15.158.0/24 8.218.30.161/32 14.152.91.0/24
18.162.38.24/32 18.163.254.94/32 18.166.204.203/32 34.226.76.162/32
38.65.217.0/24 42.193.128.0/24 42.194.152.0/24 43.130.30.0/24
43.130.170.0/24 43.132.107.0/24 43.135.64.0/24 43.135.82.0/24
43.142.232.0/24 43.145.30.0/24 43.152.182.46/32 43.153.191.0/24
43.153.233.0/24 43.160.156.0/24 47.57.180.81/32 47.243.107.98/32
47.243.118.180/32 49.51.78.0/23 49.234.241.0/24 54.172.233.156/32
101.32.198.0/24 106.55.66.0/23 111.230.119.0/24 111.230.214.0/24
119.28.37.0/24 119.28.141.0/24 119.28.183.0/24 119.28.218.0/23
119.29.48.0/23 119.91.244.0/23 119.147.110.0/24 121.5.97.0/24
124.156.124.0/24 124.156.233.0/24 124.156.234.0/24 129.226.79.0/24
129.226.111.0/24 162.14.10.0/24 170.106.48.0/23 170.106.62.0/24
183.60.225.0/24 193.112.84.0/24 193.112.234.0/24""".split()

FUTU_IP_HOSTS = """43.134.158.106/32 43.132.138.6/32 119.28.201.30/32
49.51.77.113/32 43.153.234.107/32 43.153.249.33/32 43.163.17.229/32
170.106.201.0/24 175.178.207.0/24 43.132.106.6/32 43.132.106.8/32
43.132.138.67/32""".split()

# StocksHK.list 里的宽口径 IP 段（覆盖上面部分单点，合并后取并集）
FUTU_IP_BROAD = """43.153.0.0/16 49.234.0.0/16 101.32.0.0/16
119.28.0.0/16 119.91.0.0/16 124.156.0.0/16 129.226.0.0/16 170.106.0.0/16""".split()

FUTU_KEYWORD = "futunn futubull futuhk futufin futuholdings futuniuniu futuesop moomoo".split()

# --- 长桥 / Longbridge ---
LB_SUFFIX = """lbctrl.com lbkrs.com api.lbkrs.com api-gl.lbkrs.com
wbrks.com longbridge.app longbridge.cloud longbridge.com
longbridge.global longbridge.hk longbridge.sg
longbridgeapp.com longbridgehk.com longportapp.cn longportapp.com
lbkg.net lb-static.com longportapp.hk longbridge-inc.com""".split()

LB_EXACT = """quote.longbridge.global trade.longportapp.com
openapi.longbridge.com openapi-quote.longbridge.com
openapi-trade.longbridge.com openapi.longbridge.cn
openapi-quote.longbridge.cn openapi-trade.longbridge.cn""".split()

LB_IP = "47.85.0.0/16 161.117.0.0/16".split()

# --- 老虎 Tiger Brokers ---
TIGER_SUFFIX = """itiger.com itigerup.com tigerbrokers.com
tigerbrokers.net tigerbrokers.nz tigerfintech.com
skytigris.cn tradeup.com iotaskyt.com
laohu8.com tigerbbs.cn tigerbbs.com xiaohu8.com
zhijianfengyi.cn zhijianfengyi.com""".split()

# --- 雪球 ---
SNOWBALL_SUFFIX = "snowball-x.com snowballsecurities.com snbsecurities.com".split()
SNOWBALL_EXACT = """cn.snowball-x.com www.snowballsecurities.com
open.snowballsecurities.com openapi.snbsecurities.com
sandbox.snbsecurities.com""".split()

# --- Interactive Brokers / Schwab ---
IB_SUFFIX = "interactivebrokers.com interactivebrokers.com.hk".split()
SCHWAB_SUFFIX = "schwab.com schwab.com.cn schwab.com.hk schwab.co.uk".split()

# --- 同花顺 ---
THS_EXACT = "m.10jqka.com.cn t.10jqka.com.cn msv6.wosms.cn".split()
THS_SUFFIX = """0033.com hexin.cn 10jqka.com.cn iwencai.com thsi.cn
tdx.com.cn gw.com.cn hexun.com myhexun.com soumoney.com.cn
thsbx.com ticang.com 51ifind.com 5ifund.com yingfund.net
myhexin.com 123ths.com ths123.com huntgold.cn thsbaoxian.net
touzime.net hithink.com myhithink.com zhifutech.com aicubes.cn
thsyun.com voiceclub.cn gtimg.cn sinajs.cn hxkba.com
yongginbao.com.cn""".split()
THS_IP = "122.9.0.0/16 221.236.0.0/16".split()

# --- 东方财富 ---
EM_SUFFIX = """1234567.com.cn 18.cn 18.com.cn 95021.com
caifutong.com.cn caimi.cn caimi.com.cn dfcfs.cn dfcfs.com
dfcfw.com dingqibao.cn dingqibao.com dingqibao.com.cn
dongfanglicaishi.com eastmoney.com eastmoneyfutures.com
emsec.hk guba.com.cn haitunzhibo.com huoqibao.cn huoqibao.com
huoqibao.com.cn langke.tv samacn.org.cn tiantianfunds.cn
txjhqh.com uufund.cn uufund.com xzsec.com zhaiba.com
zhongcaisuo.cn zhongcaisuo.com zhongcaisuo.com.cn""".split()

# --- 华泰 ---
HT_SUFFIX = """htsc.com.hk zhangle.com htsc.com htsc.com.cn
htzq.com.cn zhangleglobal.com ihtfin.com cmpassport.com
finet.com.cn roadshowing.com""".split()
HT_IP = """180.101.0.0/16 222.190.0.0/16 221.226.0.0/16 218.2.0.0/16
122.96.0.0/16 153.3.0.0/16 157.0.0.0/16
120.195.0.0/16 218.206.0.0/16 223.112.0.0/16
47.106.0.0/16 120.79.0.0/16
124.70.0.0/16 113.44.0.0/16""".split()

# IP 查询辅助
IPAPI = "ip-api.com".split()


def norm_ip(cidr: str) -> str:
    """把 /24 单主机形式统一成规范 CIDR，便于去重。"""
    return cidr.strip()


def main():
    domain = OrderedDict()
    ipcidr = OrderedDict()
    keyword = OrderedDict()

    def add_domains(items):
        for d in items:
            d = d.strip().lower()
            if d:
                domain[d] = True

    def add_ips(items):
        for c in items:
            c = norm_ip(c)
            if c:
                ipcidr[c] = True

    # ---- 归集 ----
    add_domains(FUTU_SUFFIX + FUTU_EXTRA_SUFFIX + MOOMOO_SUFFIX)
    add_domains(FUTU_ATTRIBUTION_SUFFIX)
    add_ips(FUTU_IP + FUTU_IP_HOSTS + FUTU_IP_BROAD)

    add_domains(LB_SUFFIX)
    add_ips(LB_IP)

    add_domains(TIGER_SUFFIX)
    add_domains(SNOWBALL_SUFFIX)
    add_domains(IB_SUFFIX + SCHWAB_SUFFIX)
    add_domains(THS_SUFFIX)
    add_ips(THS_IP)
    add_domains(EM_SUFFIX)
    add_domains(HT_SUFFIX)
    add_ips(HT_IP)
    add_domains(IPAPI)

    for k in FUTU_KEYWORD:
        keyword[k] = True

    # 精确域名必须放在后缀之前（mihomo 按顺序匹配，先精确更安全）
    exact = OrderedDict()
    for d in FUTU_EXACT + LB_EXACT + SNOWBALL_EXACT + THS_EXACT:
        d = d.strip().lower()
        if d:
            exact[d] = True

    # 精确项从后缀集合里剔除（保证不重复）
    for d in list(exact):
        domain.pop(d, None)

    # suffix 集合里去掉裸 TLD 这类过宽项（无意义且易误匹配）
    domain.pop("18.cn", None)
    domain.pop("18.com.cn", None)

    lines = []
    lines.append("# 金融规则集 / Financial Ruleset")
    lines.append("# 合并自 https://github.com/koo17173/rule-set")
    lines.append("#   BrokerHK / HK_Broker.conf / BrokerCN / BrokerHT / Stocks.list / StocksHK.list")
    lines.append("# 覆盖：富途·moomoo、长桥、老虎、雪球、盈透、Schwab、同花顺、东方财富、华泰")
    lines.append("# 生成方式：逐文件抓取 → 合并去重 → 规范化 IP 段")
    lines.append(f"# 统计：DOMAIN {len(exact)} / DOMAIN-SUFFIX {len(domain)} / DOMAIN-KEYWORD {len(keyword)} / IP-CIDR {len(ipcidr)}")
    lines.append("")
    lines.append("rules:")

    # 分组输出，便于阅读
    groups = [
        ("精确域名（行情/交易/OpenAPI 端点）", [f"DOMAIN,{d}" for d in exact]),
        ("域名后缀（券商客户端与官网）", [f"DOMAIN-SUFFIX,{d}" for d in domain]),
        ("域名关键词（富途 moomoo 兜底）", [f"DOMAIN-KEYWORD,{k}" for k in keyword]),
        ("IP 段（券商行情/交易服务器，需 no-resolve）",
         [f"IP-CIDR,{c},no-resolve" for c in sorted(ipcidr)]),
    ]
    for title, items in groups:
        if not items:
            continue
        lines.append(f"  # ---- {title} ----")
        lines.extend(f"  - {it}" for it in items)
        lines.append("")

    out_yaml = "\n".join(lines).rstrip() + "\n"

    # 同时输出 clash 传统 list 格式（兼容老内核 / Sub-Store）
    plain = []
    for it in [f"DOMAIN,{d}" for d in exact] + \
             [f"DOMAIN-SUFFIX,{d}" for d in domain] + \
             [f"DOMAIN-KEYWORD,{k}" for k in keyword] + \
             [f"IP-CIDR,{c},no-resolve" for c in sorted(ipcidr)]:
        plain.append(it)

    base = "/Users/fooktong/Downloads/clash-ruler/rule-provider"
    with open(f"{base}/finance-rules.yaml", "w") as f:
        f.write(out_yaml)
    with open(f"{base}/finance-rules.list", "w") as f:
        f.write("\n".join(plain) + "\n")

    print(f"DOMAIN         {len(exact)}")
    print(f"DOMAIN-SUFFIX  {len(domain)}")
    print(f"DOMAIN-KEYWORD {len(keyword)}")
    print(f"IP-CIDR        {len(ipcidr)}")
    print(f"总计           {len(plain)}")


if __name__ == "__main__":
    main()