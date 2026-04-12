"""
新闻聚合简报 — 从 Launch 文件夹中的新闻渠道拉取并归纳
支持: 少数派、36氪、钛媒体、新周刊、知乎热榜、Hacker News、IT之家、爱范儿
TODO: LINUX DO（需 cookie）
"""

import os
import urllib.request
import json
import re
import ssl
import math as _math
import logging as _logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import jieba
_logging.getLogger("jieba").setLevel(_logging.WARNING)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

ctx = ssl.create_default_context()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}


def get(url, extra_headers=None):
    h = {**HEADERS}
    if extra_headers:
        h.update(extra_headers)
    req = urllib.request.Request(url, headers=h)
    resp = urllib.request.urlopen(req, timeout=15, context=ctx)
    return resp.read().decode("utf-8", errors="replace")


# ── 摘要去噪 ──────────────────────────────────────────

_DESC_NOISE = [
    r'查看全文$', r'查看原文$', r'阅读全文$', r'阅读原文$',
    r'点击查看$', r'展开全文$', r'\[图片\]',
    r'Matrix首页推荐.*?观点。', r'IT之家注：[^））]*[））]',
    r'\(IT之家注：[^)]*\)?', r'（IT之家注：[^）]*）?',
    r'IT之家注：[^。，）)]*', r'IT之家\s*\d+\s*月\s*\d+\s*日消息[，,]?',
    r'#欢迎关注爱范儿.*$', r'爱范儿（微信号：ifanr）.*$',
]
_DESC_NOISE_RE = re.compile('|'.join(_DESC_NOISE))


def clean_desc(text):
    """清理摘要中的噪音文本"""
    text = _DESC_NOISE_RE.sub('', text).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def parse_rss(xml_text):
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        desc = item.findtext("description", "")
        desc_clean = re.sub(r"<[^>]+>", "", desc).strip()
        pub = item.findtext("pubDate", "")
        items.append({"title": title, "link": link, "desc": desc_clean, "pub": pub})
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        title = entry.findtext("atom:title", "", ns)
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = entry.findtext("atom:summary", "", ns) or entry.findtext("atom:content", "", ns)
        summary_clean = re.sub(r"<[^>]+>", "", summary).strip() if summary else ""
        pub = entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns)
        items.append({"title": title, "link": link, "desc": summary_clean, "pub": pub})
    return items


# ── 渠道拉取 ──────────────────────────────────────────

def fetch_sspai():
    """少数派 RSS"""
    xml = get("https://sspai.com/feed")
    items = parse_rss(xml)
    results = []
    for it in items[:12]:
        results.append({
            "source": "少数派",
            "title": it["title"],
            "link": it["link"],
            "desc": clean_desc(it["desc"][:200]),
        })
    return results


def fetch_36kr():
    """36氪 RSS，失败时走 newsflash API"""
    # 先尝试 RSS
    try:
        raw = get("https://36kr.com/feed")
        if "<html" not in raw[:200].lower():
            raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
            raw = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", raw)
            items = parse_rss(raw)
            if items:
                results = []
                for it in items[:12]:
                    results.append({
                        "source": "36氪",
                        "title": it["title"],
                        "link": it["link"],
                        "desc": clean_desc(it["desc"][:200]),
                    })
                return results
    except Exception:
        pass
    # 备用: newsflash API (快讯)
    try:
        data = json.loads(get("https://36kr.com/api/newsflash?per_page=15"))
        items = data.get("data", {}).get("items", [])
        results = []
        for it in items[:12]:
            results.append({
                "source": "36氪",
                "title": it.get("title", "") or it.get("description", "")[:80],
                "link": f"https://36kr.com/newsflashes/{it.get('id', '')}",
                "desc": clean_desc((it.get("description", "") or "")[:200]),
            })
        return results
    except Exception:
        return []


def fetch_tmtpost():
    """钛媒体 RSS"""
    xml = get("https://www.tmtpost.com/rss.xml")
    items = parse_rss(xml)
    results = []
    for it in items[:12]:
        results.append({
            "source": "钛媒体",
            "title": it["title"],
            "link": it["link"],
            "desc": clean_desc(it["desc"][:200]),
        })
    return results


def fetch_neweekly():
    """新周刊 HTML"""
    html = get("https://www.neweekly.com.cn/")
    titles = re.findall(r"<h\d[^>]*>([^<]{5,80})</h\d>", html)
    # extract links near titles
    links = re.findall(r'href="(/article/detail\.html\?[^"]+)"', html)
    results = []
    seen = set()
    for t in titles:
        t = t.strip()
        if t not in seen:
            seen.add(t)
            link = f"https://www.neweekly.com.cn"
            results.append({
                "source": "新周刊",
                "title": t,
                "link": link,
                "desc": "",
            })
    return results[:10]


def fetch_hackernews():
    """Hacker News Top Stories (public API)"""
    ids = json.loads(get("https://hacker-news.firebaseio.com/v0/topstories.json"))
    results = []
    for sid in ids[:15]:
        try:
            item = json.loads(get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json"))
            title = item.get("title", "")
            url = item.get("url", f"https://news.ycombinator.com/item?id={sid}")
            score = item.get("score", 0)
            if title:
                results.append({
                    "source": f"Hacker News [{score} pts]",
                    "title": title,
                    "link": url,
                    "desc": "",
                })
        except Exception:
            continue
    return results


def fetch_ithome():
    """IT之家 RSS"""
    xml = get("https://www.ithome.com/rss/")
    items = parse_rss(xml)
    results = []
    for it in items[:12]:
        desc = re.sub(r"<[^>]+>", "", it["desc"]).strip()[:200]
        results.append({
            "source": "IT之家",
            "title": it["title"],
            "link": it["link"],
            "desc": desc,
        })
    return results


def fetch_ifanr():
    """爱范儿 RSS"""
    xml = get("https://www.ifanr.com/feed")
    items = parse_rss(xml)
    results = []
    for it in items[:10]:
        desc = re.sub(r"<[^>]+>", "", it["desc"]).strip()[:200]
        results.append({
            "source": "爱范儿",
            "title": it["title"],
            "link": it["link"],
            "desc": desc,
        })
    return results


def fetch_producthunt():
    """Product Hunt Atom Feed"""
    xml = get("https://www.producthunt.com/feed")
    # Atom feed: <entry><title>...</title><link href="..."/></entry>
    titles = re.findall(r"<entry>.*?<title[^>]*>([^<]+)</title>", xml, re.S)
    links = re.findall(r"<entry>.*?<link[^>]*href=['\"]([^'\"]+)['\"]", xml, re.S)
    summaries = re.findall(r"<entry>.*?<content[^>]*>([^<]*)</content>", xml, re.S)
    results = []
    for i, title in enumerate(titles[:12]):
        link = links[i] if i < len(links) else "https://www.producthunt.com"
        desc = summaries[i].strip()[:200] if i < len(summaries) else ""
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        results.append({
            "source": "Product Hunt",
            "title": title.strip(),
            "link": link,
            "desc": clean_desc(desc),
        })
    return results


def fetch_github_trending():
    """GitHub Trending (HTML scraping)"""
    html = get("https://github.com/trending")
    articles = re.findall(
        r'<article class="Box-row">(.*?)</article>', html, re.S
    )
    results = []
    for art_html in articles[:12]:
        # repo link
        m_link = re.search(r'<h2[^>]*>.*?<a href="(/[^"]+)"', art_html, re.S)
        if not m_link:
            continue
        repo_path = m_link.group(1).strip()
        repo_name = repo_path.lstrip("/").replace(" ", "")
        # description
        m_desc = re.search(r'<p class="[^"]*">(.*?)</p>', art_html, re.S)
        desc = re.sub(r"<[^>]+>", "", m_desc.group(1)).strip()[:200] if m_desc else ""
        # language
        m_lang = re.search(r'itemprop="programmingLanguage">([^<]+)', art_html)
        lang = m_lang.group(1).strip() if m_lang else ""
        # stars today
        m_stars = re.search(r'(\d[\d,]*)\s*stars today', art_html)
        star_str = f"⭐{m_stars.group(1)}" if m_stars else ""
        # source 标签: GitHub [Python · ⭐123]
        meta_parts = [p for p in [lang, star_str] if p]
        meta = " · ".join(meta_parts)
        source_tag = f"GitHub [{meta}]" if meta else "GitHub"
        results.append({
            "source": source_tag,
            "title": repo_name,
            "link": f"https://github.com{repo_path}",
            "desc": desc,
        })
    return results


def fetch_juejin():
    """稀土掘金 热榜 API"""
    url = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot&spider=0"
    data = json.loads(get(url))
    results = []
    for item in data.get("data", [])[:12]:
        content = item.get("content", {})
        cid = content.get("content_id", "")
        title = content.get("title", "")
        if title:
            results.append({
                "source": "掘金",
                "title": title,
                "link": f"https://juejin.cn/post/{cid}",
                "desc": "",
            })
    return results


def _make_rss_fetcher(source_name, feed_url, limit=10, academic=False):
    """工厂函数: 生成标准 RSS/Atom 拉取器
    academic=True: 添加 🔬 标记，强制归类到 "学术/AI 研究"
    """
    def fetcher():
        xml = get(feed_url)
        items = parse_rss(xml)
        results = []
        for it in items[:limit]:
            desc = re.sub(r"<[^>]+>", "", it["desc"]).strip()[:200]
            item = {
                "source": f"🔬 {source_name}" if academic else source_name,
                "title": it["title"],
                "link": it["link"],
                "desc": clean_desc(desc),
            }
            if academic:
                item["topic"] = "学术/AI 研究"  # 强制归类
            results.append(item)
        return results
    fetcher.__doc__ = f"{source_name} RSS"
    return fetcher

# 批量生成 RSS fetcher
fetch_ruanyifeng   = _make_rss_fetcher("阮一峰", "http://feeds.feedburner.com/ruanyifeng", 8)
fetch_v2ex         = _make_rss_fetcher("V2EX", "https://v2ex.com/index.xml", 12)
fetch_solidot      = _make_rss_fetcher("Solidot", "https://www.solidot.org/index.rss", 10)
fetch_hellogithub  = _make_rss_fetcher("HelloGitHub", "https://hellogithub.com/rss", 10)
fetch_appinn       = _make_rss_fetcher("小众软件", "https://feeds.appinn.com/appinns/", 10)
fetch_meituan_tech = _make_rss_fetcher("美团技术", "https://tech.meituan.com/feed", 8)
fetch_huxiu        = _make_rss_fetcher("虎嗅", "https://rss.huxiu.com/", 10)
fetch_zaobao_cn    = _make_rss_fetcher("联合早报", "https://plink.anyfeeder.com/zaobao/realtime/china", 10)
fetch_zaobao_world = _make_rss_fetcher("联合早报(国际)", "https://plink.anyfeeder.com/zaobao/realtime/world", 10)
fetch_mittr_cn     = _make_rss_fetcher("MIT科技评论", "https://plink.anyfeeder.com/mittrchina/hot", 8)
fetch_wsj_cn       = _make_rss_fetcher("华尔街日报", "https://plink.anyfeeder.com/wsj/cn", 8)
fetch_fortune_cn   = _make_rss_fetcher("财富中文", "https://plink.anyfeeder.com/fortunechina/shangye", 8)
fetch_sanlian      = _make_rss_fetcher("三联生活", "https://plink.anyfeeder.com/weixin/lifeweek", 8)
fetch_duku         = _make_rss_fetcher("读库", "https://plink.anyfeeder.com/weixin/dukuxiaobao", 8)
fetch_yousa        = _make_rss_fetcher("Yousa DD", "https://yousali.com/index.xml", 10)
fetch_positive_news = _make_rss_fetcher("Positive News", "https://www.positive.news/feed/", 10)
fetch_coder_cafe  = _make_rss_fetcher("The Coder Cafe", "https://read.thecoder.cafe/feed", 10)
fetch_economist    = _make_rss_fetcher("经济学人", "https://economistnew.buzzing.cc/feed.xml", 10)
fetch_supertechfans = _make_rss_fetcher("SuperTechFans", "https://www.supertechfans.com/cn/index.xml", 10)
fetch_juya_ai_daily = _make_rss_fetcher("橘鸦AI早报", "https://imjuya.github.io/juya-ai-daily/rss.xml", 10)
fetch_openai_news   = _make_rss_fetcher("OpenAI News", "https://openai.com/news/rss.xml", 10)
fetch_coolshell     = _make_rss_fetcher("酷壳", "http://coolshell.cn/feed", 8)
fetch_programthink  = _make_rss_fetcher("编程随想", "https://feeds2.feedburner.com/programthink", 8)
fetch_codingnow     = _make_rss_fetcher("云风", "http://blog.codingnow.com/atom.xml", 8)
fetch_bmpi          = _make_rss_fetcher("构建我的被动收入", "https://www.bmpi.dev/index.xml", 8)
fetch_onevcat       = _make_rss_fetcher("OneV's Den", "http://onevcat.com/atom.xml", 8)
fetch_williamlong   = _make_rss_fetcher("月光博客", "https://www.williamlong.info/rss.xml", 8)
fetch_tw93_weekly   = _make_rss_fetcher("潮流周刊", "https://weekly.tw93.fun/rss.xml", 8)
fetch_the_verge     = _make_rss_fetcher("The Verge", "https://www.theverge.com/rss/index.xml", 10)
fetch_wired         = _make_rss_fetcher("Wired", "https://www.wired.com/feed/rss", 10)
fetch_stratechery   = _make_rss_fetcher("Stratechery", "https://stratechery.com/feed/", 8)
fetch_techcrunch    = _make_rss_fetcher("TechCrunch", "https://techcrunch.com/feed/", 10)

def fetch_arxiv_by_category(category, limit=8):
    """arXiv 获取器: 优先官方 RSS，无内容时回退 RSSHub"""
    cat_code = category.replace("cs.", "")
    
    # 方案B: 官方 RSS（工作日有内容）
    try:
        xml = get(f"https://export.arxiv.org/rss/{category}")
        items = parse_rss(xml)
        if items:
            results = []
            for it in items[:limit]:
                desc = re.sub(r"<[^>]+>", "", it["desc"]).strip()[:200]
                results.append({
                    "source": f"🔬 arXiv-{cat_code}",
                    "title": it["title"],
                    "link": it["link"],
                    "desc": clean_desc(desc),
                    "topic": "学术/AI 研究",
                })
            return results
    except Exception:
        pass
    
    # 方案A 回退: 分类列表页抓取（周末/官方 RSS 空时）
    try:
        list_url = f"https://arxiv.org/list/{category}/recent"
        html = get(list_url)
        ids = re.findall(r'arXiv:(\d{4}\.\d{4,})', html)
        titles = re.findall(r'Title:</span>\s*(.*?)\s*</div>', html, re.S)
        
        results = []
        for i, title in enumerate(titles[:limit]):
            title_clean = re.sub(r"<[^>]+>", "", title).strip()
            arxiv_id = ids[i] if i < len(ids) else ""
            if title_clean and arxiv_id:
                results.append({
                    "source": f"🔬 arXiv-{cat_code}",
                    "title": title_clean,
                    "link": f"https://arxiv.org/abs/{arxiv_id}",
                    "desc": "",
                    "topic": "学术/AI 研究",
                })
        return results
    except Exception:
        pass
    
    return []

# arXiv fetcher 函数（对应书签 CS 文件夹全部 14 个子类）
def fetch_arxiv_lg(): return fetch_arxiv_by_category("cs.LG", 8)
def fetch_arxiv_se(): return fetch_arxiv_by_category("cs.SE", 5)
def fetch_arxiv_et(): return fetch_arxiv_by_category("cs.ET", 5)
def fetch_arxiv_sy(): return fetch_arxiv_by_category("cs.SY", 5)
def fetch_arxiv_dc(): return fetch_arxiv_by_category("cs.DC", 5)
def fetch_arxiv_db(): return fetch_arxiv_by_category("cs.DB", 5)
def fetch_arxiv_cc(): return fetch_arxiv_by_category("cs.CC", 5)
def fetch_arxiv_ce(): return fetch_arxiv_by_category("cs.CE", 5)
def fetch_arxiv_cy(): return fetch_arxiv_by_category("cs.CY", 5)
def fetch_arxiv_ds(): return fetch_arxiv_by_category("cs.DS", 5)
def fetch_arxiv_lo(): return fetch_arxiv_by_category("cs.LO", 5)
def fetch_arxiv_ma(): return fetch_arxiv_by_category("cs.MA", 5)
def fetch_arxiv_pl(): return fetch_arxiv_by_category("cs.PL", 5)
def fetch_arxiv_pf(): return fetch_arxiv_by_category("cs.PF", 5)

def fetch_deeplearning_batch():
    """DeepLearning.ai The Batch (HTML scraping)"""
    html = get("https://www.deeplearning.ai/the-batch/")
    # 提取文章区块: 寻找包含标题链接的结构
    results = []
    # Pattern: 文章通常有 h2/h3 标题 + 链接
    # 尝试多种模式
    articles = re.findall(r'<article[^>]*>(.*?)</article>', html, re.S)
    for art in articles[:8]:
        # 找标题
        title_m = re.search(r'<h[23][^>]*>(?:<a[^>]*>)?([^<]+)', art)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
        # 找链接
        link_m = re.search(r'href=\"(https://www\.deeplearning\.ai/the-batch/[^\"]+)\"', art)
        link = link_m.group(1) if link_m else "https://www.deeplearning.ai/the-batch/"
        # 找摘要
        desc_m = re.search(r'<p[^>]*>(.*?)</p>', art, re.S)
        desc = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()[:160] if desc_m else ""
        if title and len(title) > 10:
            results.append({
                "source": "The Batch",
                "title": title,
                "link": link,
                "desc": clean_desc(desc),
            })
    # 如果没找到，尝试全局搜索
    if not results:
        titles = re.findall(r'<h[23][^>]*>([^<]+)</h[23]>', html)
        for t in titles[:6]:
            t_clean = re.sub(r'<[^>]+>', '', t).strip()
            if len(t_clean) > 15:
                results.append({
                    "source": "The Batch",
                    "title": t_clean,
                    "link": "https://www.deeplearning.ai/the-batch/",
                    "desc": "",
                })
    return results

def fetch_hf_papers():
    """Hugging Face Daily Papers"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    url = f"https://huggingface.co/papers/date/{today_str}"
    try:
        html = get(url)
    except:
        # 如果今天没有，尝试昨天
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"https://huggingface.co/papers/date/{yesterday}"
        html = get(url)
    
    results = []
    # 提取论文: href="/papers/2604.08377" ... >Title</a>
    papers = re.findall(r'href=\"(/papers/\d{4}\.\d{5,})\"[^>]*>([^<]+)</a>', html)
    seen = set()
    for paper_id, title in papers[:12]:
        if title in seen or len(title) < 10:
            continue
        seen.add(title)
        results.append({
            "source": "🔬 HF Papers",
            "title": title.strip(),
            "link": f"https://huggingface.co{paper_id}",
            "desc": "",
            "topic": "学术/AI 研究"  # 强制归类到学术
        })
    return results

def fetch_epoch_ai():
    """Epoch AI - 研究报告更新"""
    html = get("https://epoch.ai/")
    results = []
    # 找最新发布的研究/文章
    articles = re.findall(r'<a[^>]*href=\"(/[^\"]+)\"[^>]*>([^<]{20,200})</a>', html)
    seen = set()
    for link_path, title in articles[:8]:
        title_clean = re.sub(r'<[^>]+>', '', title).strip()
        if title_clean in seen or len(title_clean) < 20:
            continue
        seen.add(title_clean)
        link = f"https://epoch.ai{link_path}" if link_path.startswith('/') else link_path
        results.append({
            "source": "Epoch AI",
            "title": title_clean,
            "link": link,
            "desc": "",
        })
    return results[:5]  # 限制数量，因为是低频更新


def fetch_zhihu():
    """知乎热榜 (需 cookie)"""
    cookie_path = r"C:\Users\nonep\Desktop\win11\bookmarks\.zhihu_cookie"
    parts = []
    for line in open(cookie_path, encoding="utf-8"):
        line = line.strip()
        if "=" in line:
            parts.append(line)
    cookie_str = "; ".join(parts)

    url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=20&desktop=true"
    data = json.loads(get(url, extra_headers={
        "Referer": "https://www.zhihu.com/hot",
        "Cookie": cookie_str,
    }))
    results = []
    for item in data.get("data", [])[:20]:
        target = item.get("target", {})
        title = target.get("title", "")
        excerpt = target.get("excerpt", "")[:200]
        detail = item.get("detail_text", "")
        qid = target.get("id", "")
        results.append({
            "source": f"知乎 [{detail}]",
            "title": title,
            "link": f"https://www.zhihu.com/question/{qid}",
            "desc": clean_desc(excerpt),
        })
    return results


# ── 主题分类 ──────────────────────────────────────────

TOPIC_KEYWORDS = {
    "学术/AI 研究": [],  # 由 fetcher 强制指定 topic，不走关键词匹配
    "AI / 人工智能": ["ai", "人工智能", "大模型", "agent", "claude", "gpt", "openai", "机器学习",
                     "深度学习", "token", "自动驾驶", "智能", "芯片", "算力",
                     "llm", "neural", "transformer", "diffusion", "ml", "model",
                     "copilot", "gemini", "anthropic", "cursor"],
    "科技产品": ["手机", "iphone", "苹果", "华为", "小米", "oppo", "vivo", "三星", "平板",
               "耳机", "眼镜", "ar", "vr", "穿戴", "相机", "电脑", "笔记本", "显卡",
               "apple", "google", "pixel", "macbook", "gpu", "nvidia", "amd"],
    "互联网 / 商业": ["融资", "ipo", "上市", "估值", "创业", "36氪首发", "收购", "裁员",
                    "营收", "亏损", "电商", "直播", "抖音", "微信", "拼多多", "淘宝",
                    "滴滴", "美团", "字节", "腾讯", "阿里", "百度", "京东",
                    "startup", "acquisition", "ycombinator", "yc", "series", "funding"],
    "财经 / 宏观": ["股", "基金", "利率", "通胀", "gdp", "美联储", "央行", "货币",
                   "关税", "贸易", "经济", "金融", "投资", "房价", "楼市"],
    "社会 / 文化": ["教育", "医疗", "女性", "青年", "文化", "电影", "音乐", "书",
                   "综艺", "纪录片", "旅行", "城市", "县城", "人口", "婚姻"],
    "新能源 / 汽车": ["新能源", "电车", "电动", "充电", "储能", "光伏", "风电", "锂电",
                    "电池", "特斯拉", "比亚迪", "蔚来", "小鹏", "理想", "低空"],
    "游戏 / 娱乐": ["游戏", "steam", "主机", "ps5", "switch", "动漫", "二次元", "权志龙",
                    "game", "gaming", "nintendo", "playstation", "xbox"],
    "国际 / 地缘": ["美国", "伊朗", "俄罗斯", "乌克兰", "台湾", "日本", "韩国", "欧洲",
                    "北约", "中东", "海峡", "制裁", "军事", "霍尔木兹", "停火", "宇航",
                    "south korea", "china", "europe", "russia", "ukraine", "iran"],
    "体育": ["英超", "足球", "篮球", "赛季", "nba", "联赛", "冠军", "摩托车", "赛车"],
    "生活 / 健康": ["减肥", "健身", "饮食", "睡眠", "保健", "医学", "心理", "食品"],
}

# ── 聚类: Sentence Embedding (主) / TF-IDF (fallback) ──

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _EMBED_MODEL = None  # 延迟加载
    _USE_EMBEDDING = True
except ImportError:
    _USE_EMBEDDING = False

def _get_embed_model():
    """延迟加载 embedding 模型，避免启动时卡顿"""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        print("  加载语义模型 (首次较慢)...")
        _EMBED_MODEL = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _EMBED_MODEL

def _embed_cosine(emb_a, emb_b):
    """两个 embedding 向量的余弦相似度"""
    dot = float(np.dot(emb_a, emb_b))
    norm = float(np.linalg.norm(emb_a) * np.linalg.norm(emb_b))
    return dot / norm if norm > 0 else 0.0

# ── TF-IDF fallback ──

_STOP_WORDS = {
    "如何", "看待", "什么", "为什么", "怎么", "可以", "应该", "已经",
    "哪些", "关于", "这个", "那个", "一个", "我们", "他们", "自己",
    "为何", "还是", "真的", "到底", "是否", "就是", "居然", "意味",
    "表示", "认为", "显示", "以来", "方面", "成为", "带来", "能够",
    "the", "and", "for", "how", "what", "why", "this", "that",
    "are", "was", "has", "its", "will", "can", "from",
    "with", "you", "your", "not", "but", "all", "have", "been",
}

for _w in ["英伟达", "比亚迪", "特斯拉", "小鹏汽车", "蔚来汽车", "理想汽车",
          "OpenAI", "ChatGPT", "DeepSeek", "Anthropic", "Perplexity",
          "GitHub", "Copilot", "Gemini", "Claude", "Llama", "Mistral"]:
    jieba.add_word(_w)

def _tokenize(title):
    tokens = []
    for w in jieba.cut(title):
        w = w.strip().lower()
        if len(w) < 2 or w in _STOP_WORDS:
            continue
        tokens.append(w)
    return tokens

def _build_tfidf(titles):
    docs = [_tokenize(t) for t in titles]
    n = len(docs)
    if n == 0:
        return []
    df = {}
    for tokens in docs:
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    vectors = []
    for tokens in docs:
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        vec = {}
        for t, count in tf.items():
            vec[t] = (1 + _math.log(count)) * _math.log(n / df[t])
        vectors.append(vec)
    return vectors

def _tfidf_cosine(v1, v2):
    if not v1 or not v2:
        return 0.0
    common = set(v1.keys()) & set(v2.keys())
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    norm1 = _math.sqrt(sum(v * v for v in v1.values()))
    norm2 = _math.sqrt(sum(v * v for v in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

# ── 统一接口 ──

def _topic_similarity(title_a, title_b):
    """语义相似度 (embedding 优先, TF-IDF fallback)"""
    if _USE_EMBEDDING:
        model = _get_embed_model()
        embs = model.encode([title_a, title_b])
        return _embed_cosine(embs[0], embs[1])
    vecs = _build_tfidf([title_a, title_b])
    return _tfidf_cosine(vecs[0], vecs[1]) if len(vecs) >= 2 else 0.0


def cluster_articles(articles, threshold=None):
    """语义聚类: embedding (阈值 0.6) 或 TF-IDF fallback (阈值 0.15)
    新文章只和每个 cluster 的 lead 比较，避免雪球效应"""
    if not articles:
        return []

    use_emb = _USE_EMBEDDING
    if threshold is None:
        threshold = 0.6 if use_emb else 0.15

    titles = [a["title"] for a in articles]

    if use_emb:
        model = _get_embed_model()
        vectors = model.encode(titles, show_progress_bar=False)
        sim_fn = _embed_cosine
    else:
        vectors = _build_tfidf(titles)
        sim_fn = _tfidf_cosine

    clusters = []  # [(lead_idx, [other_idxs])]
    for i in range(len(articles)):
        best_score = 0.0
        best_cluster = -1
        for ci, (lead_idx, others_idx) in enumerate(clusters):
            score = sim_fn(vectors[i], vectors[lead_idx])
            if score > best_score:
                best_score = score
                best_cluster = ci
        if best_score >= threshold and best_cluster >= 0:
            clusters[best_cluster][1].append(i)
        else:
            clusters.append((i, []))

    return [(articles[lead], [articles[j] for j in others])
            for lead, others in clusters]


def classify(article):
    """给文章打标签。如果文章有强制 topic 字段，直接返回该分类"""
    # 强制分类优先（学术源等）
    forced_topic = article.get("topic")
    if forced_topic and forced_topic in TOPIC_KEYWORDS:
        return [forced_topic]
    
    # 正常关键词匹配
    text = (article["title"] + " " + article.get("desc", "")).lower()
    tags = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                tags.append(topic)
                break
    if not tags:
        tags.append("其他")
    return tags


# ── 数据收集 ──────────────────────────────────────────

SOURCES = [
    ("少数派", fetch_sspai),
    ("36氪", fetch_36kr),
    ("钛媒体", fetch_tmtpost),
    ("新周刊", fetch_neweekly),
    ("知乎热榜", fetch_zhihu),
    ("Hacker News", fetch_hackernews),
    ("IT之家", fetch_ithome),
    ("爱范儿", fetch_ifanr),
    ("Product Hunt", fetch_producthunt),
    ("GitHub Trending", fetch_github_trending),
    ("掘金", fetch_juejin),
    ("阮一峰", fetch_ruanyifeng),
    ("V2EX", fetch_v2ex),
    ("Solidot", fetch_solidot),
    ("HelloGitHub", fetch_hellogithub),
    ("小众软件", fetch_appinn),
    ("美团技术", fetch_meituan_tech),
    ("虎嗅", fetch_huxiu),
    ("联合早报", fetch_zaobao_cn),
    ("联合早报(国际)", fetch_zaobao_world),
    ("MIT科技评论", fetch_mittr_cn),
    ("华尔街日报", fetch_wsj_cn),
    ("财富中文", fetch_fortune_cn),
    ("三联生活", fetch_sanlian),
    ("读库", fetch_duku),
    ("Yousa DD", fetch_yousa),
    ("Positive News", fetch_positive_news),
    ("The Coder Cafe", fetch_coder_cafe),
    ("经济学人", fetch_economist),
    ("SuperTechFans", fetch_supertechfans),
    ("橘鸦AI早报", fetch_juya_ai_daily),
    ("OpenAI News", fetch_openai_news),
    ("酷壳", fetch_coolshell),
    ("编程随想", fetch_programthink),
    ("云风", fetch_codingnow),
    ("构建我的被动收入", fetch_bmpi),
    ("OneV's Den", fetch_onevcat),
    ("月光博客", fetch_williamlong),
    ("潮流周刊", fetch_tw93_weekly),
    ("The Verge", fetch_the_verge),
    ("Wired", fetch_wired),
    ("Stratechery", fetch_stratechery),
    ("TechCrunch", fetch_techcrunch),
    ("The Batch", fetch_deeplearning_batch),
    ("🔬 HF Papers", fetch_hf_papers),
    ("Epoch AI", fetch_epoch_ai),
    ("arXiv-ML", fetch_arxiv_lg),
    ("arXiv-SE", fetch_arxiv_se),
    ("arXiv-ET", fetch_arxiv_et),
    ("arXiv-SY", fetch_arxiv_sy),
    ("arXiv-DC", fetch_arxiv_dc),
    ("arXiv-DB", fetch_arxiv_db),
    ("arXiv-CC", fetch_arxiv_cc),
    ("arXiv-CE", fetch_arxiv_ce),
    ("arXiv-CY", fetch_arxiv_cy),
    ("arXiv-DS", fetch_arxiv_ds),
    ("arXiv-LO", fetch_arxiv_lo),
    ("arXiv-MA", fetch_arxiv_ma),
    ("arXiv-PL", fetch_arxiv_pl),
    ("arXiv-PF", fetch_arxiv_pf),
]


def collect():
    """拉取全部渠道、分类，返回结构化数据"""
    all_articles = []
    for name, fetcher in SOURCES:
        try:
            articles = fetcher()
            all_articles.extend(articles)
            print(f"  [OK] {name}: {len(articles)} 条")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")

    # 跨分类去重: 每篇文章只归入首个匹配的分类
    topic_groups = {}
    assigned = set()  # 已分配的文章标题
    # 先收集所有分类
    art_topics = []  # [(art, [tags])]
    for art in all_articles:
        art_topics.append((art, classify(art)))
    # 按分类优先级分配 (非"其他"优先)
    for art, tags in art_topics:
        for tag in tags:
            topic_groups.setdefault(tag, [])
    for art, tags in art_topics:
        primary = tags[0]  # 首个匹配分类
        if art["title"] not in assigned:
            topic_groups.setdefault(primary, []).append(art)
            assigned.add(art["title"])
        else:
            # 已在别的分类出现过，跳过
            pass

    sorted_topics = sorted(topic_groups.items(),
                           key=lambda x: (x[0] == "其他", -len(x[1])))
    # 去掉空分类
    sorted_topics = [(t, arts) for t, arts in sorted_topics if arts]
    return all_articles, sorted_topics


# ── 趋势感知 ──────────────────────────────────────────

def detect_trends(all_articles, lookback_days=3):
    """扫描过去 N 天的归档，找今日标题在往日的同话题命中
    返回 {article_title: 出现天数}"""
    import os
    from datetime import timedelta

    today = datetime.now().date()
    prev_day_titles = {}  # {day_str: [titles]}

    for d in range(1, lookback_days + 1):
        day = (today - timedelta(days=d)).strftime("%Y-%m-%d")
        md_path = os.path.join(ARCHIVE_DIR, f"news-digest-{day}.md")
        if os.path.exists(md_path):
            with open(md_path, encoding="utf-8") as f:
                titles = re.findall(r'\*\*(.+?)\*\*', f.read())
                prev_day_titles[day] = titles

    if not prev_day_titles:
        return {}

    # 对每篇今日文章，检查在哪些历史日有同话题
    article_trend = {}  # {title: days_count}
    for art in all_articles:
        days_hit = set()
        for day, prev_titles in prev_day_titles.items():
            for pt in prev_titles:
                if _topic_similarity(art["title"], pt) >= 0.35:
                    days_hit.add(day)
                    break  # 这天有就够了
        if days_hit:
            article_trend[art["title"]] = len(days_hit) + 1  # +1 for today

    return article_trend


def get_article_trend(art, trends):
    """检查文章的趋势天数"""
    return trends.get(art["title"], 0)


# ── 评分 & 降噪 ──────────────────────────────────────

# 每个分类最多展示多少个 cluster（0 = 不限制）
BUDGET_PER_TOPIC = 7  # Miller's Law: 人类短期记忆 7±2

def _parse_heat(art):
    """从 source 字段提取热度数值 (万)"""
    src = art.get("source", "")
    # 知乎: "知乎 [2384 万热度]"
    m = re.search(r'(\d+)\s*万热度', src)
    if m:
        return int(m.group(1))
    # HN: "Hacker News [312 pts]"
    m = re.search(r'(\d+)\s*pts', src)
    if m:
        return int(m.group(1)) / 100  # 粗略换算到"万"量级
    return 0


def score_cluster(lead, others, trends=None):
    """给一个聚类打分，返回 (总分, 分项详情dict)
    算法: log(出现次数 + 1)  — 参考 Reddit/Lemmy 对数排序
    出现次数 = cluster 内不同源的数量"""
    all_arts = [lead] + others

    sources = set(a["source"].split(" [")[0] for a in all_arts)
    n_sources = len(sources)
    total = _math.log(n_sources + 1)

    detail = {
        "sources": n_sources,
        "source_names": sorted(sources),
        "total": round(total, 2),
    }
    return total, detail


# ── Markdown 渲染 ────────────────────────────────────

def render_md(all_articles, sorted_topics, today):
    lines = [
        f"# 每日新闻简报 · {today}",
        "",
        f"来源: 少数派 / 36氪 / 钛媒体 / 新周刊 / 知乎 | 共 {len(all_articles)} 条",
        "", "---", "",
    ]
    for topic, articles in sorted_topics:
        lines.append(f"## {topic}（{len(articles)} 条）")
        lines.append("")
        seen = set()
        for art in articles:
            if art["title"] in seen:
                continue
            seen.add(art["title"])
            lines.append(f"- **{art['title']}** — {art['source']}")
            if art["desc"]:
                lines.append(f"  > {art['desc'][:120]}")
            if art["link"]:
                lines.append(f"  {art['link']}")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


# ── HTML 渲染 (Notion 风格) ───────────────────────────

TOPIC_META = {
    "学术/AI 研究":   ("🔬", "#9065e0"),  # 学术专用紫色
    "AI / 人工智能":  ("🤖", "#448aff"),
    "科技产品":       ("📱", "#337ea9"),
    "互联网 / 商业":  ("🏢", "#d9730d"),
    "财经 / 宏观":    ("📈", "#0f7b6c"),
    "社会 / 文化":    ("🎭", "#cb3837"),
    "新能源 / 汽车":  ("🔋", "#0f7b6c"),
    "游戏 / 娱乐":    ("🎮", "#9065e0"),
    "国际 / 地缘":    ("🌍", "#d44c47"),
    "体育":           ("⚽", "#337ea9"),
    "生活 / 健康":    ("💊", "#448aff"),
    "其他":           ("📌", "#787774"),
}

SOURCE_COLORS = {
    "少数派": "#0f7b6c",
    "36氪": "#337ea9",
    "钛媒体": "#d44c47",
    "新周刊": "#d9730d",
    "知乎":  "#448aff",
    "Hacker News": "#ff6600",
    "IT之家": "#d44c47",
    "爱范儿": "#0f7b6c",
    "Product Hunt": "#da552f",
    "GitHub": "#333333",
    "掘金": "#1e80ff",
    "阮一峰": "#337ea9",
    "V2EX": "#778087",
    "Solidot": "#009688",
    "HelloGitHub": "#333333",
    "小众软件": "#0f7b6c",
    "美团技术": "#ffc107",
    "虎嗅": "#d44c47",
    "联合早报": "#d44c47",
    "联合早报(国际)": "#d44c47",
    "MIT科技评论": "#9065e0",
    "华尔街日报": "#333333",
    "财富中文": "#d9730d",
    "三联生活": "#337ea9",
    "读库": "#0f7b6c",
    "Yousa DD": "#6c5ce7",
    "Positive News": "#27ae60",
    "The Coder Cafe": "#e67e22",
    "经济学人": "#c0392b",
    "SuperTechFans": "#e74c3c",
    "橘鸦AI早报": "#9b59b6",
    "OpenAI News": "#10a37f",
    "酷壳": "#e67e22",
    "编程随想": "#c0392b",
    "云风": "#16a085",
    "构建我的被动收入": "#27ae60",
    "OneV's Den": "#e74c3c",
    "月光博客": "#f39c12",
    "潮流周刊": "#9b59b6",
    "The Verge": "#0099f5",
    "Wired": "#e74c3c",
    "Stratechery": "#34495e",
    "TechCrunch": "#00aaff",
    "The Batch": "#0056d2",
    "HF Papers": "#ffbd3d",
    "Epoch AI": "#2eaadc",
    "🔬 HF Papers": "#ffbd3d",
    "🔬 arXiv-ML": "#9065e0",
    "🔬 arXiv-SE": "#9065e0",
    "🔬 arXiv-ET": "#9065e0",
    "🔬 arXiv-SY": "#9065e0",
    "🔬 arXiv-DC": "#9065e0",
    "🔬 arXiv-DB": "#9065e0",
    "🔬 arXiv-CC": "#9065e0",
    "🔬 arXiv-CE": "#9065e0",
    "🔬 arXiv-CY": "#9065e0",
    "🔬 arXiv-DS": "#9065e0",
    "🔬 arXiv-LO": "#9065e0",
    "🔬 arXiv-MA": "#9065e0",
    "🔬 arXiv-PL": "#9065e0",
    "🔬 arXiv-PF": "#9065e0",
}


def render_html(all_articles, sorted_topics, today, trends=None):
    import html as h
    trends = trends or {}

    source_counts = {}
    for art in all_articles:
        s = art["source"].split(" [")[0]
        source_counts[s] = source_counts.get(s, 0) + 1

    stats_html = ""
    for src, cnt in source_counts.items():
        color = SOURCE_COLORS.get(src, "#787774")
        stats_html += f'<div class="stat"><div class="stat-val" style="color:{color}">{cnt}</div><div class="stat-lbl">{h.escape(src)}</div></div>\n'

    nav = ""
    for topic, articles in sorted_topics:
        icon, color = TOPIC_META.get(topic, ("📌", "#787774"))
        tid = topic.replace(" ", "").replace("/", "-")
        nav += f'<a href="#{tid}" class="pill" style="--c:{color}">{icon} {h.escape(topic)}<span class="cnt">{len(articles)}</span></a>\n'

    def _render_row(art, num="", score_detail=None):
        title_esc = h.escape(art["title"])
        source_raw = art["source"].split(" [")[0]
        source_detail = ""
        if " [" in art["source"]:
            source_detail = art["source"].split(" [")[1].rstrip("]")
        source_esc = h.escape(source_raw)
        src_color = SOURCE_COLORS.get(source_raw, "#787774")
        desc_esc = h.escape(art["desc"][:160]) if art.get("desc") else ""
        link = h.escape(art.get("link", ""))
        heat = f'<span class="heat">{h.escape(source_detail)}</span>' if source_detail else ""
        desc_block = f'<p class="row-desc">{desc_esc}</p>' if desc_esc else ""
        num_badge = f'<span class="row-num">{num}</span>' if num else ""
        # 源数量徽章（点击展开源列表）
        score_tag = ""
        if score_detail and score_detail["sources"] > 1:
            n = score_detail["sources"]
            names = '、'.join(h.escape(s) for s in score_detail["source_names"])
            score_tag = f'<span class="score-badge" onclick="event.preventDefault();event.stopPropagation();this.classList.toggle(\'expanded\')" title="{names}">{n}源<span class="source-list">{names}</span></span>'
        return f'''<a href="{link}" target="_blank" rel="noopener" class="row">
  {num_badge}
  <div class="row-main">
    <h3 class="row-title">{title_esc}</h3>
    {desc_block}
  </div>
  <div class="row-meta">
    {score_tag}
    <span class="tag" style="--tc:{src_color}">{source_esc}</span>
    {heat}
  </div>
</a>'''

    def _render_related(art, num=""):
        source_raw = art["source"].split(" [")[0]
        src_color = SOURCE_COLORS.get(source_raw, "#787774")
        link = h.escape(art.get("link", ""))
        num_badge = f'<span class="sub-num">{num}</span>' if num else ""
        return f'''<a href="{link}" target="_blank" rel="noopener" class="related-row">
  {num_badge}
  <span class="tag" style="--tc:{src_color}">{h.escape(source_raw)}</span>
  <span class="related-title">{h.escape(art["title"])}</span>
</a>'''

    sections = ""
    for topic, articles in sorted_topics:
        icon, color = TOPIC_META.get(topic, ("📌", "#787774"))
        tid = topic.replace(" ", "").replace("/", "-")

        # 去重
        deduped = []
        seen = set()
        for art in articles:
            if art["title"] not in seen:
                seen.add(art["title"])
                deduped.append(art)

        clusters = cluster_articles(deduped)

        # 评分 & 排序
        scored = []
        for lead, others in clusters:
            total, detail = score_cluster(lead, others, trends)
            scored.append((lead, others, total, detail))
        scored.sort(key=lambda x: -x[2])  # 分高的在前

        # 分层: 首屏 BUDGET_PER_TOPIC 条 + 展开区再来一批
        # 学术分类 cluster 总数 14（首屏 7，展开 7），其他分类 7+7
        if topic == "学术/AI 研究":
            first_page = scored[:7] if BUDGET_PER_TOPIC > 0 else scored
            more_page = scored[7:14] if BUDGET_PER_TOPIC > 0 else []  # 7 条，总数 14
        else:
            first_page = scored[:BUDGET_PER_TOPIC] if BUDGET_PER_TOPIC > 0 else scored
            more_page = scored[BUDGET_PER_TOPIC:BUDGET_PER_TOPIC * 2] if BUDGET_PER_TOPIC > 0 else []
        n_hidden = len(scored) - len(first_page) - len(more_page)  # 完全隐藏的

        def _render_cluster_rows(cluster_list, start_idx=1):
            html_out = ""
            for idx_offset, (lead, others, total, detail) in enumerate(cluster_list):
                idx = start_idx + idx_offset
                html_out += _render_row(lead, str(idx), score_detail=detail)
                if others:
                    # 关联项展开：首屏 7 条，点击展开显示全部（不限制数量）
                    related_first = others[:7]
                    related_more = others[7:] if len(others) > 7 else []
                    
                    related_html = "\n".join(_render_related(a, f"{idx}.{j}") for j, a in enumerate(related_first, 1))
                    
                    # 关联项展开按钮（显示全部剩余）
                    more_related = ""
                    if related_more:
                        more_related_html = "\n".join(_render_related(a, f"{idx}.{j}") for j, a in enumerate(related_more, 8))
                        n_related_more = len(related_more)
                        more_related = f'''<div class="related-more" id="related-{idx}" style="display:none">{more_related_html}</div>
<button class="show-related-btn" onclick="var el=document.getElementById('related-{idx}');if(el.style.display==='none'){{el.style.display='block';this.textContent='收起';}}else{{el.style.display='none';this.textContent='展开 {n_related_more} 条关联 ↓';}}" >展开 {n_related_more} 条关联 ↓</button>'''
                    
                    html_out += f'<div class="related">{related_html}{more_related}</div>\n'
            return html_out

        rows_first = _render_cluster_rows(first_page, 1)
        rows_more = _render_cluster_rows(more_page, len(first_page) + 1) if more_page else ""

        n_total_shown = len(first_page) + len(more_page)
        total_arts = sum(1 + len(others) for _, others, _, _ in first_page)
        count_label = f"{total_arts}"
        if len(first_page) != total_arts:
            count_label = f"{len(first_page)} groups · {total_arts} articles"

        # Show more 按钮
        more_section = ""
        if rows_more:
            n_more = len(more_page)
            more_section = f'''<div class="more-rows" id="more-{tid}" style="display:none">{rows_more}</div>
<button class="show-more-btn" onclick="var el=document.getElementById('more-{tid}');if(el.style.display==='none'){{el.style.display='block';this.textContent='收起';}}else{{el.style.display='none';this.textContent='展开 {n_more} 条 ↓';}}" >展开 {n_more} 条 ↓</button>'''

        sections += f'''<section id="{tid}">
  <div class="sec-head">
    <span class="sec-icon" style="--ic:{color}">{icon}</span>
    <h2>{h.escape(topic)}</h2>
    <span class="sec-count">{count_label}</span>
  </div>
  <div class="rows">{rows_first}</div>
  {more_section}
</section>
'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Digest · {today}</title>
<style>
/* ═══════════════════════════════════════════════════
   Notion-inspired Design System
   Warm minimalism · Serif headings · Soft surfaces
   ═══════════════════════════════════════════════════ */

/* ── Tokens (Light — default, Notion is light-first) ── */
:root, [data-theme="light"] {{
  --bg:         #ffffff;
  --bg-hover:   #f7f6f3;
  --bg-gray:    #f1f1ef;
  --bg-nav:     rgba(255,255,255,0.92);
  --border:     #e9e9e7;
  --border-heavy:#ddddd9;
  --text:       #37352f;
  --text-sec:   #6b6b6b;
  --text-light: #9b9a97;
  --accent:     #2eaadc;
  --shadow:     0 1px 3px rgba(0,0,0,0.04), 0 0 0 1px rgba(0,0,0,0.03);
  --shadow-lg:  0 4px 16px rgba(0,0,0,0.06);
  color-scheme: light;
}}

/* ── Tokens (Dark) ── */
[data-theme="dark"] {{
  --bg:         #191919;
  --bg-hover:   #212121;
  --bg-gray:    #252525;
  --bg-nav:     rgba(25,25,25,0.92);
  --border:     #2f2f2f;
  --border-heavy:#3a3a3a;
  --text:       #e3e2df;
  --text-sec:   #9b9a97;
  --text-light: #6b6b6b;
  --accent:     #529cca;
  --shadow:     0 1px 3px rgba(0,0,0,0.15), 0 0 0 1px rgba(255,255,255,0.04);
  --shadow-lg:  0 4px 16px rgba(0,0,0,0.2);
  color-scheme: dark;
}}

/* ── Design Styles ── */
[data-style="notion"] {{
  --font-title: 'Georgia', 'Noto Serif SC', 'Source Han Serif CN', 'Songti SC', serif;
  --accent:     #2eaadc;
  --radius:     3px;
  --max-w:      900px;
  --shadow:     0 1px 2px rgba(0,0,0,0.05);
}}

[data-style="apple"] {{
  --font-title: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
  --accent:     #007AFF;
  --radius:     12px;
  --max-w:      980px;
  --shadow:     0 2px 8px rgba(0,0,0,0.08);
}}

[data-style="cursor"] {{
  --font-title: 'SF Mono', 'Monaco', 'Consolas', monospace;
  --accent:     #58A6FF;
  --radius:     6px;
  --max-w:      1200px;
  --shadow:     0 4px 12px rgba(0,0,0,0.15);
}}

[data-style="figma"] {{
  --font-title: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --accent:     #0D99FF;
  --radius:     8px;
  --max-w:      1100px;
  --shadow:     0 8px 24px rgba(0,0,0,0.12);
}}

[data-style="github"] {{
  --font-title: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --accent:     #0969DA;
  --radius:     6px;
  --max-w:      1012px;
  --shadow:     0 1px 3px rgba(0,0,0,0.12);
}}

[data-style="miro"] {{
  --font-title: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --accent:     #4262FF;
  --radius:     16px;
  --max-w:      1300px;
  --shadow:     0 12px 32px rgba(0,0,0,0.1);
}}

/* ── Shared tokens ── */
:root {{
  --font-title: 'Georgia', 'Noto Serif SC', 'Source Han Serif CN',
                'Songti SC', serif;
  --font-body:  -apple-system, 'SF Pro Text', 'Segoe UI', 'PingFang SC',
                'Microsoft YaHei', sans-serif;
  --font-mono:  'SFMono-Regular', 'Cascadia Code', 'Consolas', monospace;
  --radius:     4px;
  --radius-lg:  8px;
  --ease:       200ms ease;
  --max-w:      780px;
}}

/* ── Reset ── */
*,*::before,*::after {{ margin:0; padding:0; box-sizing:border-box; }}
html {{ scroll-behavior:smooth; -webkit-font-smoothing:antialiased; }}
body {{
  font-family: var(--font-body);
  background: var(--bg);
  color: var(--text);
  font-size: 15px;
  line-height: 1.65;
  min-height: 100vh;
}}

/* ── Page wrapper ── */
.page {{
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 0 48px;
}}
@media (max-width: 840px) {{
  .page {{ padding: 0 20px; }}
}}

/* ── Header ── */
.hdr {{
  padding: 56px 0 24px;
}}
.hdr h1 {{
  font-family: var(--font-title);
  font-size: 2.2rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
  color: var(--text);
}}
.hdr .sub {{
  margin-top: 6px;
  font-size: 0.88rem;
  color: var(--text-light);
}}
.hdr .sub span {{
  color: var(--text-sec);
  font-weight: 500;
}}

/* ── Divider ── */
.divider {{
  height: 1px;
  background: var(--border);
  margin: 0;
}}

/* ── Nav pills ── */
.nav {{
  position: sticky; top: 0; z-index: 50;
  background: var(--bg-nav);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  margin: 0 -48px;
  padding-left: 48px;
  padding-right: 48px;
}}
@media (max-width: 840px) {{
  .nav {{ margin: 0 -20px; padding-left: 20px; padding-right: 20px; }}
}}
.nav-scroll {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}}
.pill {{
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  border-radius: var(--radius);
  background: transparent;
  border: none;
  color: var(--text-sec);
  font-size: 0.8rem;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
  transition: all var(--ease);
}}
.pill:hover {{
  background: var(--bg-gray);
  color: var(--text);
}}
.pill .cnt {{
  font-family: var(--font-mono);
  font-size: 0.68rem;
  color: var(--text-light);
  margin-left: 2px;
}}

/* ── Content ── */
.content {{ padding: 32px 0 64px; }}

section {{ margin-bottom: 40px; }}
.sec-head {{
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 4px;
  padding: 6px 0;
}}
.sec-icon {{
  width: 24px; height: 24px;
  display: grid; place-items: center;
  font-size: 0.95rem;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--ic, #787774) 12%, transparent);
  flex-shrink: 0;
}}
.sec-head h2 {{
  font-family: var(--font-title);
  font-size: 1.1rem;
  font-weight: 600;
  flex: 1;
  letter-spacing: -0.01em;
}}
.sec-count {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--text-light);
}}

/* ── Rows ── */
.rows {{ display: flex; flex-direction: column; }}
.row {{
  display: flex;
  gap: 16px;
  align-items: flex-start;
  padding: 12px 8px;
  border-radius: var(--radius);
  text-decoration: none;
  color: inherit;
  transition: background var(--ease);
}}
.row:hover {{
  background: var(--bg-hover);
}}
.row-num {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-light);
  min-width: 22px;
  text-align: center;
  flex-shrink: 0;
  line-height: 1;
  padding-top: 3px;
}}
.row:hover .row-num {{ color: var(--accent); }}
.trend {{
  display: inline-block;
  font-size: 0.66rem;
  font-weight: 600;
  color: #e67e22;
  background: rgba(230, 126, 34, 0.1);
  padding: 1px 6px;
  border-radius: var(--radius);
  margin-right: 6px;
  vertical-align: middle;
  letter-spacing: -0.02em;
}}
[data-theme="dark"] .trend {{
  color: #f39c12;
  background: rgba(243, 156, 18, 0.15);
}}
.score-badge {{
  font-family: var(--font-mono);
  font-size: 0.6rem;
  color: var(--text-light);
  background: var(--bg-gray);
  padding: 1px 5px;
  border-radius: var(--radius);
  margin-right: 4px;
  cursor: pointer;
  position: relative;
}}
.row:hover .score-badge {{ color: var(--accent); }}
.source-list {{
  display: none;
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 8px 12px;
  font-size: 0.75rem;
  color: var(--text);
  white-space: nowrap;
  z-index: 10;
  font-family: var(--font-body);
}}
.score-badge.expanded .source-list {{
  display: block;
}}
.show-more-btn {{
  display: block;
  width: 100%;
  padding: 8px 0;
  margin: 4px 0 0;
  background: var(--bg-gray);
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-sec);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
}}
.show-more-btn:hover {{
  background: var(--bg-hover);
  color: var(--accent);
  border-color: var(--accent);
}}
.more-rows {{
  animation: fadeIn 0.2s ease;
}}
@keyframes fadeIn {{
  from {{ opacity: 0; transform: translateY(-4px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
.sub-num {{
  font-family: var(--font-mono);
  font-size: 0.66rem;
  color: var(--text-light);
  min-width: 28px;
  text-align: right;
  flex-shrink: 0;
  padding-right: 2px;
}}
.related-row:hover .sub-num {{ color: var(--accent); }}
.row-main {{ flex: 1; min-width: 0; }}
.row-title {{
  font-size: 0.92rem;
  font-weight: 500;
  line-height: 1.5;
  color: var(--text);
  transition: color var(--ease);
}}
.row:hover .row-title {{ color: var(--accent); }}
.row-desc {{
  font-size: 0.82rem;
  color: var(--text-sec);
  line-height: 1.55;
  margin-top: 3px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}
.row-meta {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
  padding-top: 2px;
}}
.tag {{
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--tc, var(--text-light));
  white-space: nowrap;
}}
.heat {{
  font-family: var(--font-mono);
  font-size: 0.66rem;
  color: var(--text-light);
  background: var(--bg-gray);
  padding: 1px 6px;
  border-radius: var(--radius);
  white-space: nowrap;
}}

/* ── Related (clustered) rows ── */
.related {{
  margin-left: 20px;
  padding-left: 12px;
  border-left: 2px solid var(--border);
  margin-bottom: 4px;
}}
.related-row {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 8px;
  border-radius: var(--radius);
  text-decoration: none;
  color: inherit;
  transition: background var(--ease);
}}
.related-row:hover {{
  background: var(--bg-hover);
}}
.related-title {{
  font-size: 0.82rem;
  color: var(--text-sec);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.related-row:hover .related-title {{
  color: var(--accent);
}}
.related-more {{
  animation: fadeIn 0.2s ease;
}}
.show-related-btn {{
  margin-left: 20px;
  margin-bottom: 8px;
  padding: 4px 12px;
  font-size: 0.75rem;
  color: var(--text-sec);
  background: var(--bg-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--ease);
}}
.show-related-btn:hover {{
  background: var(--bg-hover);
  color: var(--accent);
}}

/* ── Footer ── */
.ftr {{
  padding: 20px 0;
  border-top: 1px solid var(--border);
  text-align: center;
  color: var(--text-light);
  font-size: 0.75rem;
}}

/* ── Theme toggle ── */
.theme-btn {{
  position: fixed;
  bottom: 24px; right: 24px;
  z-index: 100;
  width: 36px; height: 36px;
  border-radius: 50%;
  background: var(--bg);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  cursor: pointer;
  display: grid; place-items: center;
  font-size: 1rem;
  transition: all var(--ease);
  color: var(--text-sec);
}}
.theme-btn:hover {{
  border-color: var(--accent);
  transform: scale(1.06);
}}
.style-btn {{
  position: fixed;
  bottom: 24px; right: 72px;
  z-index: 100;
  width: 36px; height: 36px;
  border-radius: 50%;
  background: var(--bg);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  cursor: pointer;
  display: grid; place-items: center;
  font-size: 1rem;
  transition: all var(--ease);
  color: var(--text-sec);
}}
.style-btn:hover {{
  border-color: var(--accent);
  transform: scale(1.06);
}}

/* ── Style-specific overrides ── */
[data-style="apple"] .hdr h1 {{
  font-weight: 600;
  letter-spacing: -0.015em;
}}
[data-style="apple"] .nav {{
  border-bottom: 1px solid rgba(0,0,0,0.1);
}}
[data-style="apple"] .row {{
  padding: 16px 12px;
}}
[data-style="apple"] .pill {{
  border-radius: 20px;
}}

[data-style="cursor"] .hdr h1 {{
  font-family: 'SF Mono', monospace;
  font-weight: 500;
  letter-spacing: -0.02em;
}}
[data-style="cursor"] .row {{
  border: 1px solid var(--border);
  margin: 8px 0;
  background: rgba(255,255,255,0.02);
}}
[data-style="cursor"] .pill {{
  background: rgba(88, 166, 255, 0.1);
  border: 1px solid rgba(88, 166, 255, 0.2);
}}

[data-style="figma"] .hdr h1 {{
  font-weight: 700;
  background: linear-gradient(135deg, #0D99FF, #A259FF);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}
[data-style="figma"] .row {{
  border-radius: var(--radius);
  background: linear-gradient(135deg, rgba(13, 153, 255, 0.05), rgba(162, 89, 255, 0.05));
}}
[data-style="figma"] .pill {{
  background: rgba(13, 153, 255, 0.1);
  font-weight: 600;
}}

[data-style="github"] .hdr h1 {{
  font-weight: 600;
  font-size: 2rem;
}}
[data-style="github"] .nav {{
  background: var(--bg-gray);
  border-bottom: 1px solid var(--border-heavy);
}}
[data-style="github"] .row {{
  border-bottom: 1px solid var(--border);
  border-radius: 0;
  padding: 12px 0;
}}
[data-style="github"] .pill {{
  background: var(--bg-gray);
  border: 1px solid var(--border);
}}

[data-style="miro"] .hdr h1 {{
  font-weight: 700;
  font-size: 2.4rem;
}}
[data-style="miro"] .row {{
  background: white;
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  margin: 8px 0;
  padding: 20px 16px;
}}
[data-style="miro"] .pill {{
  background: linear-gradient(135deg, #4262FF, #A259FF);
  color: white;
  border-radius: 20px;
}}
[data-style="miro"] .sec-icon {{
  background: linear-gradient(135deg, #4262FF, #A259FF);
  color: white;
}}
</style>
</head>
<body>
<div class="page">

  <div class="hdr">
    <h1>Daily Digest</h1>
    <p class="sub"><span>{len(all_articles)}</span> stories &middot; {today}</p>
  </div>

  <div class="divider"></div>

  <nav class="nav"><div class="nav-scroll">
  {nav}
  </div></nav>

  <div class="content">
  {sections}
  </div>

  <div class="ftr">Generated by news_digest.py</div>

</div>

<button class="theme-btn" id="themeToggle" aria-label="Toggle theme">🌙</button>
<button class="style-btn" id="styleToggle" aria-label="Toggle style">🎨</button>

<script>
(function() {{
  const themeBtn = document.getElementById('themeToggle');
  const styleBtn = document.getElementById('styleToggle');
  const html = document.documentElement;
  const themeIcons = {{ dark: '🌙', light: '☀\ufe0f' }};
  const styles = ['notion', 'apple', 'cursor', 'figma', 'github', 'miro'];
  const styleNames = {{ notion: 'Notion', apple: 'Apple', cursor: 'Cursor', figma: 'Figma', github: 'GitHub', miro: 'Miro' }};
  const styleIcons = {{ notion: '📝', apple: '🍎', cursor: '🎯', figma: '🎨', github: '🐙', miro: '🔄' }};

  function sysTheme() {{
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }}

  function autoTheme() {{
    const hour = new Date().getHours();
    // 18:00-06:00 为暗夜模式
    return (hour >= 18 || hour < 6) ? 'dark' : 'light';
  }}

  function applyTheme(t) {{
    html.setAttribute('data-theme', t);
    themeBtn.textContent = themeIcons[t];
    themeBtn.title = t === 'dark' ? '切换到亮色模式' : '切换到暗夜模式';
    localStorage.setItem('digest-theme', t);
  }}

  function applyStyle(s) {{
    html.setAttribute('data-style', s);
    styleBtn.textContent = styleIcons[s];
    styleBtn.title = '当前主题: ' + styleNames[s];
    localStorage.setItem('digest-style', s);
  }}

  // 初始化: 优先使用用户手动选择，否则根据时间自动切换
  const userTheme = localStorage.getItem('digest-theme');
  if (userTheme) {{
    applyTheme(userTheme);
  }} else {{
    applyTheme(autoTheme());
  }}
  applyStyle(localStorage.getItem('digest-style') || 'notion');

  // 每分钟检查一次是否需要自动切换（仅当用户未手动设置时）
  setInterval(function() {{
    if (!localStorage.getItem('digest-theme')) {{
      const currentTheme = html.getAttribute('data-theme');
      const shouldTheme = autoTheme();
      if (currentTheme !== shouldTheme) {{
        applyTheme(shouldTheme);
      }}
    }}
  }}, 60000);

  themeBtn.addEventListener('click', function() {{
    const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
    // 用户手动切换后，保存偏好，不再自动切换
    localStorage.setItem('digest-theme', newTheme);
  }});

  styleBtn.addEventListener('click', function() {{
    const currentStyle = html.getAttribute('data-style');
    const currentIndex = styles.indexOf(currentStyle);
    const nextIndex = (currentIndex + 1) % styles.length;
    applyStyle(styles[nextIndex]);
  }});
}})()
</script>
</body>
</html>'''


# ── 保存 ─────────────────────────────────────────────

ARCHIVE_DIR = r"C:\Users\nonep\Desktop\win11\news-digest\docs"


def save_digest(md, html):
    import os
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    md_path = os.path.join(ARCHIVE_DIR, f"news-digest-{today}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    html_path = os.path.join(ARCHIVE_DIR, f"news-digest-{today}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return md_path, html_path


def today_digest_path():
    import os
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(ARCHIVE_DIR, f"news-digest-{today}.md")


def already_done():
    import os
    return os.path.exists(today_digest_path())


def self_check_academic_expansion(html_path):
    """自检: 验证学术分类展开区是否为 7 条（用 Playwright 真实点击）"""
    if not PLAYWRIGHT_AVAILABLE:
        print("  [自检] 跳过: 需安装 playwright (pip install playwright && playwright install chromium)")
        return
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            file_url = "file:///" + html_path.replace('\\', '/')
            page.goto(file_url)
            
            # 截图学术分类区域
            academic_section = page.locator("#学术-AI研究")
            academic_section.screenshot(path="c:/Users/nonep/Desktop/win11/news-archive/academic_screenshot.png")
            
            # 找到学术分类的展开按钮并点击
            button = page.locator("text=/展开.*条.*↓/").first
            if not button.is_visible():
                print("  [自检] ⚠️ 学术分类无展开按钮 (聚类后少于 7 条)")
                browser.close()
                return
            
            # 统计点击前的数量（只算学术分类 section 内的 cluster rows）
            rows_before = page.locator("#学术-AI研究 .rows .row-num").count()
            
            # 点击展开
            button.click()
            page.wait_for_timeout(500)  # 等待动画
            
            # 统计点击后的数量
            rows_after = page.locator("#学术-AI研究 .row-num").count()
            expanded_count = rows_after - rows_before
            
            if expanded_count == 7:
                print(f"  [自检] ✅ 学术分类: 首屏 {rows_before} 条，展开区 {expanded_count} 条 (符合预期)")
            else:
                print(f"  [自检] ❌ 学术分类: 首屏 {rows_before} 条，展开区 {expanded_count} 条 (预期 7 条)")
            
            browser.close()
            
    except Exception as e:
        print(f"  [自检] ❌ 验证失败: {e}")


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv

    if already_done() and not force:
        print(f"今日简报已存在: {today_digest_path()}")
        print("如需重新生成，请加 --force 参数")
        sys.exit(0)

    print("正在拉取各渠道...")
    all_articles, sorted_topics = collect()
    today = datetime.now().strftime("%Y-%m-%d")

    if BUDGET_PER_TOPIC > 0:
        print(f"降噪预算: 每分类首屏 {BUDGET_PER_TOPIC} 组，学术分类 cluster 总数 14（首屏 7+展开 7），其他 7+7")

    md = render_md(all_articles, sorted_topics, today)
    html = render_html(all_articles, sorted_topics, today, trends=None)
    md_path, html_path = save_digest(md, html)

    print(f"\n已保存: {md_path}")
    print(f"已保存: {html_path}")
    
    # 自检学术分类展开区
    print("\n自检验证...")
    self_check_academic_expansion(html_path)
