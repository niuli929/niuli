#!/usr/bin/env python3
"""
财税知识自动采集管道 v2
=======================
自动采集财税/工商相关政策，AI 精简后入库 IMA 知识库。

数据源:
  1. 国家税务总局政策法规库 (fgk.chinatax.gov.cn) — 主力
  2. 中国政府网最新政策 (gov.cn/zhengce/zuixin) — 补充

用法:
  python tax_crawler.py                # 采集最新（每源1页）
  python tax_crawler.py --pages 3       # 每源3页
  python tax_crawler.py --source tax    # 只采税务总局
  python tax_crawler.py --source gov    # 只采中国政府网
  python tax_crawler.py --list          # 列出已采集
  python tax_crawler.py --status        # 查看统计
  python tax_crawler.py --summary       # 为最近N篇文章生成AI精简摘要
"""

import os, re, json, time, hashlib, argparse
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "douyin_output" / "tax_raw"
SUMMARY_DIR = BASE_DIR / "douyin_output" / "tax_summary"
STATE_FILE = BASE_DIR / "tax_crawler_state.json"

# 税务总局 - 最新政策文件
TAX_LIST_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100027/list.html"
TAX_LIST_PAGE = "https://fgk.chinatax.gov.cn/zcfgk/c100027/list_{page}.html"
TAX_BASE = "https://fgk.chinatax.gov.cn"

# 中国政府网 - 最新政策
GOV_LIST_URL = "https://www.gov.cn/zhengce/zuixin/"
GOV_BASE = "https://www.gov.cn"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
REQUEST_DELAY = 2

# 关键词过滤：只采集与工商财税相关的政策
RELEVANT_KEYWORDS = [
    "税", "企业", "公司", "工商", "市场", "个体", "创业", "注册",
    "登记", "经营", "发票", "财务", "会计", "征收", "所得",
    "增值", "营业", "执照", "法人", "股东", "资本", "出资",
    "年报", "注销", "代账", "记账", "申报", "缴纳", "减免",
    "优惠", "中小", "小微", "营商", "监管", "信用", "公示",
    "合规", "社保", "公积金", "劳动", "合同", "就业", "创业",
    "商事", "审批", "许可", "资质", "备案", "稽查",
]


# ============================================================
# 工具函数
# ============================================================
def safe_fetch(url: str, timeout: int = 30) -> tuple:
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return content.decode(charset, errors="replace"), None
    except (HTTPError, URLError, Exception) as e:
        return None, str(e)


def clean_html(html_text: str) -> str:
    for tag in ['script', 'style']:
        html_text = re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', html_text,
                           flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r'<[^>]+>', ' ', html_text)
    for entity, char in [('&nbsp;', ' '), ('&lt;', '<'), ('&gt;', '>'),
                          ('&amp;', '&'), ('&quot;', '"')]:
        html_text = html_text.replace(entity, char)
    html_text = re.sub(r'\s+', ' ', html_text)
    return html_text.strip()


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def is_relevant(title: str, content: str = "") -> bool:
    """判断文章是否与工商财税相关"""
    text = title + content[:500]
    for kw in RELEVANT_KEYWORDS:
        if kw in text:
            return True
    return False


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_urls": [], "articles": {}, "last_run": None}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
# 源 1: 税务总局
# ============================================================

def fetch_tax_list(pages: int = 1) -> list[dict]:
    articles = []
    for page in range(1, pages + 1):
        url = TAX_LIST_URL if page == 1 else TAX_LIST_PAGE.format(page=page)
        print(f"  [税务总局] 请求: {url}")
        html, err = safe_fetch(url)
        if err:
            print(f"  [税务总局] 失败: {err}")
            continue

        link_pat = re.compile(
            r'<a\s+href="(/zcfgk/[^"]+?/content\.html)"[^>]*?>\s*(.*?)</a>',
            re.DOTALL
        )
        for href, inner in link_pat.findall(html):
            inner_clean = clean_html(inner)
            lines = [l.strip() for l in inner_clean.split('\n') if l.strip()]
            if not lines:
                continue

            title = lines[0]
            doc_no, pub_date = "", ""
            for line in lines[1:]:
                if re.match(r'\d{4}-\d{2}-\d{2}', line):
                    pub_date = line
                elif '〔' in line or '号' in line or '函' in line:
                    doc_no = line
            if not pub_date:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', inner_clean)
                if m:
                    pub_date = m.group(1)

            articles.append({
                "title": title, "doc_no": doc_no, "pub_date": pub_date,
                "url": urljoin(TAX_BASE, href), "source": "tax",
            })

        print(f"  [税务总局] 第{page}页 {len(articles)} 条")
        if page < pages:
            time.sleep(REQUEST_DELAY)
    return articles


def fetch_tax_content(url: str) -> str | None:
    """提取税务总局文章正文"""
    html, err = safe_fetch(url)
    if err:
        return None

    # 策略：提取 <body> 中的纯文本，然后定位正文区域
    # 正文在 meta 信息（"成文日期"）之后、"特此公告"或页脚之前
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL)
    if not body_match:
        return None

    body = body_match.group(1)
    # 移除 script 和 style
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
    # 移除 HTML 注释
    body = re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL)
    # 提取纯文本
    text = re.sub(r'<[^>]+>', '\n', body)
    text = re.sub(r'&ensp;|&emsp;|&nbsp;', ' ', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    lines = text.split('\n')
    result = []
    in_content = False

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # 正文开始标志：成文日期 或 "现将"
        if '成文日期' in line or re.match(r'.*现将(有关|将).*如下', line):
            in_content = True
            result.append(line)
            continue

        # 正文结束标志
        if any(kw in line for kw in ['特此公告', '特此通知', '国家税务总局\n', '【打印】',
                                       '【下载】', '网站纠错', '主办单位', '中国政府网',
                                       '网站标识码', '京ICP', '访问统计']):
            break

        if in_content:
            # 跳过明显的 UI 文字
            if any(skip in line for skip in
                   ['扫一扫', '分享到', '个人中心', '语音播报', '登录', '注册',
                    '简 繁', 'EN', '本站热词', '首页', '总局概况', '文件 解读',
                    '高级搜索', '热门关键词', '当前位置', '阅读量', '字体：',
                    '全文有效', '收藏', '订阅', '已推送', '此稿件', '注释',
                    '关联解读', '关联文件', '关联问答', '用户登录', '忘记密码',
                    '立即注册', '没有账号']):
                continue
            result.append(line)

    if not result:
        return None

    return '\n'.join(result)


# ============================================================
# 源 2: 中国政府网
# ============================================================

def fetch_gov_list(pages: int = 1) -> list[dict]:
    articles = []
    # 注意: gov.cn/zhengce/zuixin/ 第1页就是 index.htm
    # 分页格式可能是 index_1.htm, index_2.htm
    for page in range(1, pages + 1):
        if page == 1:
            url = GOV_LIST_URL
        else:
            url = f"{GOV_LIST_URL}index_{page}.htm"

        print(f"  [中国政府网] 请求: {url}")
        html, err = safe_fetch(url)
        if err:
            print(f"  [中国政府网] 失败: {err}")
            continue

        # 结构: <a href="/zhengce/content/.../content_xxx.htm">标题</a> 后面跟着日期
        link_pat = re.compile(
            r'<a\s+href="(/zhengce/content/[^"]+?\.htm)"[^>]*?>\s*(.*?)\s*</a>',
            re.DOTALL
        )
        date_pat = re.compile(r'(\d{4}-\d{2}-\d{2})')

        matches = link_pat.findall(html)
        all_dates = date_pat.findall(html)

        seen = set()
        date_idx = 0
        for href, inner_text in matches:
            if href in seen:
                continue
            seen.add(href)

            title = clean_html(inner_text).strip()
            if not title or len(title) < 5:
                continue

            # 找这个链接后面的第一个日期
            idx = html.find(href)
            after = html[idx:idx + 500] if idx > 0 else ""
            dm = date_pat.search(after)
            pub_date = dm.group(1) if dm else ""

            articles.append({
                "title": title, "doc_no": "", "pub_date": pub_date,
                "url": urljoin(GOV_BASE, href), "source": "gov",
            })

        print(f"  [中国政府网] 第{page}页 {len(seen)} 条")
        if page < pages:
            time.sleep(REQUEST_DELAY)
    return articles


def fetch_gov_content(url: str) -> str | None:
    html, err = safe_fetch(url)
    if err:
        return None
    text = clean_html(html)
    skip = ['首页', '当前位置', '无障碍', '长者浏览', '打印本页', '关闭窗口',
            '扫一扫在手机打开', '分享：', '【字体：']
    return '\n'.join(l for l in text.split('\n')
                     if l.strip() and not any(s in l for s in skip))


# ============================================================
# 主流程
# ============================================================

def crawl(source: str, pages: int, state: dict,
          keyword_filter: bool = True) -> list[dict]:
    new_articles = []
    processed = set(state.get("processed_urls", []))

    fetch_list = fetch_tax_list if source == "tax" else fetch_gov_list
    fetch_content = fetch_tax_content if source == "tax" else fetch_gov_content

    items = fetch_list(pages)
    for item in items:
        if item["url"] in processed:
            continue

        # 关键词过滤（税务总局的全部保留，gov.cn 的需要过滤）
        if keyword_filter and source == "gov":
            if not is_relevant(item["title"]):
                continue

        print(f"\n  采集: {item['title'][:70]}...")
        content = fetch_content(item["url"])
        if content is None:
            print(f"  ⚠ 跳过（获取全文失败）")
            continue

        # gov 源二次过滤：标题过了但正文不相关也跳过
        if source == "gov" and not is_relevant(item["title"], content):
            print(f"  ⏭ 不相关，跳过")
            continue

        uid = url_hash(item["url"])
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', item["title"])[:40]
        fname = f"{item['pub_date']}_{source}_{safe_title}_{uid}.txt"
        fpath = OUTPUT_DIR / fname
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"标题: {item['title']}\n")
            if item['doc_no']:
                f.write(f"文号: {item['doc_no']}\n")
            f.write(f"日期: {item['pub_date']}\n")
            f.write(f"来源: {item['url']}\n")
            f.write(f"采集时间: {datetime.now().isoformat()}\n")
            f.write("=" * 60 + "\n\n")
            f.write(content)

        processed.add(item["url"])
        state["processed_urls"].append(item["url"])
        state["articles"][item["url"]] = {
            "title": item["title"],
            "pub_date": item["pub_date"],
            "source": source,
            "file": str(fpath),
            "collected_at": datetime.now().isoformat(),
        }
        new_articles.append({**item, "file": str(fpath)})
        print(f"  ✓ 已保存: {fname}")
        time.sleep(REQUEST_DELAY)

    return new_articles


def run_summary(days: int = 7):
    """为最近 N 天的文章生成摘要索引（供 AI 精简用）"""
    state = load_state()
    articles = state.get("articles", {})
    if not articles:
        print("还没有采集过文章。")
        return

    cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    recent = []
    for url, info in articles.items():
        try:
            d = datetime.strptime(info.get("pub_date", ""), "%Y-%m-%d")
            if (cutoff - d).days <= days:
                recent.append((d, info))
        except ValueError:
            continue

    recent.sort(key=lambda x: x[0], reverse=True)

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_DIR / f"summary_{datetime.now().strftime('%Y%m%d')}.txt"

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"# 财税政策采集摘要 ({datetime.now().strftime('%Y-%m-%d')})\n")
        f.write(f"# 最近 {days} 天，共 {len(recent)} 篇\n\n")
        for d, info in recent:
            src = {"tax": "税务总局", "gov": "中国政府网"}.get(info["source"], info["source"])
            f.write(f"## [{src}] {info['pub_date']}  {info['title']}\n")
            f.write(f"  文件: {info['file']}\n\n")

    print(f"摘要已生成: {summary_path}")
    print(f"最近 {days} 天共 {len(recent)} 篇待精简文章")
    return summary_path


def main():
    parser = argparse.ArgumentParser(description="财税知识自动采集 v2")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--source", choices=["tax", "gov", "all"], default="all")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--summary", type=int, nargs="?", const=7,
                        metavar="DAYS", help="为最近N天文章生成摘要索引（默认7天）")
    parser.add_argument("--no-filter", action="store_true",
                        help="不过滤不相关文章")
    args = parser.parse_args()

    state = load_state()

    if args.list:
        arts = state.get("articles", {})
        if not arts:
            print("还没有采集过任何文章。")
            return
        print(f"已采集 {len(arts)} 篇:\n")
        for url, info in sorted(arts.items(),
                                key=lambda x: x[1].get("pub_date", ""),
                                reverse=True):
            label = {"tax": "税务", "gov": "政府"}.get(info["source"], info["source"])
            print(f"  [{label}] {info['pub_date']}  {info['title'][:70]}")
        return

    if args.status:
        arts = state.get("articles", {})
        tax_n = sum(1 for a in arts.values() if a["source"] == "tax")
        gov_n = sum(1 for a in arts.values() if a["source"] == "gov")
        print(f"采集统计: 税务总局 {tax_n} + 中国政府网 {gov_n} = 共 {len(arts)} 篇")
        print(f"上次运行: {state.get('last_run', '从未')}")
        return

    if args.summary is not None:
        run_summary(args.summary)
        return

    # --- 采集模式 ---
    sources = []
    if args.source in ("tax", "all"):
        sources.append("tax")
    if args.source in ("gov", "all"):
        sources.append("gov")

    print("=" * 60)
    print(f"财税知识自动采集 v2")
    print(f"来源: {', '.join(sources)}")
    print(f"关键词过滤: {'关闭' if args.no_filter else '开启'}")
    print(f"开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    total = 0
    for src in sources:
        print(f"\n--- {src.upper()} ---")
        total += len(crawl(src, args.pages, state,
                          keyword_filter=not args.no_filter))

    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    print(f"\n{'='*60}")
    print(f"完成。新增 {total} 篇，累计 {len(state['articles'])} 篇")
    print(f"原始文件: {OUTPUT_DIR}")
    print(f"\n💡 下一步: 运行 'python tax_crawler.py --summary' 生成待精简索引")


if __name__ == "__main__":
    main()
