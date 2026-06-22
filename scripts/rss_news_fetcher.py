#!/usr/bin/env python3
"""
RSS News Fetcher & Summarizer  (Topic-based)
==============================================
功能：
  1. 按主题分类管理 RSS 源 (头条/科技/财经/...可无限扩展)
  2. 通过 --topics 参数选择抓取哪些主题 (或 all 全部抓取)
  3. 用 newspaper4k 提取每篇文章的完整正文
  4. 每条新闻按类别保存为一个 .md 文件
  5. 调用本地 Ollama 模型并行生成：精华总结 + 中文翻译（原文非中文时）
  6. 汇总所有总结到 summary.md（简体中文，按主题分组）

用法：
  python3 rss_news_fetcher.py                          # 抓取所有主题
  python3 rss_news_fetcher.py --topics headlines        # 只抓头条新闻
  python3 rss_news_fetcher.py --topics tech finance     # 抓科技 + 财经
  python3 rss_news_fetcher.py --topics immigration      # 只抓移民新闻
  python3 rss_news_fetcher.py --topics all --max 5      # 全部主题, 每源5条
  python3 rss_news_fetcher.py --list-topics             # 列出所有可用主题
  python3 rss_news_fetcher.py --feeds-only              # 仅抓取，不做总结
  python3 rss_news_fetcher.py --summary-only            # 仅对已有文件做总结

可供 AI Agent 修改的配置项（见下方 ===== 配置区 =====）：
  - TOPIC_FEEDS       : 按主题分类的 RSS 源字典，随时增删主题和源
  - DEFAULT_TOPICS    : 默认抓取的主题列表
  - OUTPUT_DIR        : 输出文件夹路径
  - OLLAMA_MODEL      : Ollama 模型名
  - OLLAMA_BASE_URL   : Ollama 服务地址
  - MAX_PER_FEED      : 每个源最多抓取条数
  - SUMMARY_FILENAME  : 总结文件名
"""

import os
import re
import sys
import json
import time
import html
import hashlib
import argparse
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import requests
from newspaper import Article

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                       ===== 配置区 =====                            ║
# ║           AI Agent 可直接修改以下变量来自定义行为                       ║
# ╚══════════════════════════════════════════════════════════════════════╝

# =====================================================================
#  主题分类 RSS 源 (TOPIC_FEEDS)
# =====================================================================
#  结构:  TOPIC_FEEDS = { "主题key": { "name": "...", "feeds": { ... } } }
#
#  Agent 扩展指南:
#    1. 添加新主题 → 在 TOPIC_FEEDS 末尾新增一个 key (参考底部模板)
#    2. 添加新 RSS 源 → 在对应主题的 "feeds" 字典里加一行
#    3. 删除/禁用某源 → 注释掉或删掉那一行
#    4. 在 DEFAULT_TOPICS 中设置默认抓取哪些主题
# =====================================================================

TOPIC_FEEDS = {

    # ================================================================
    #  1. 头条新闻 (headlines)
    #     全球重大事件、突发新闻、综合头条
    # ================================================================
    "headlines": {
        "name":  "头条新闻",
        "desc":  "全球重大事件、突发新闻、各大媒体头条",
        "feeds": {
            # --- 英文 ---
            "BBC Top":           "http://feeds.bbci.co.uk/news/rss.xml",
            "BBC World":         "http://feeds.bbci.co.uk/news/world/rss.xml",
            "CNN Top":           "http://rss.cnn.com/rss/edition.rss",
            "NPR Top":           "https://feeds.npr.org/1001/rss.xml",
            "Guardian World":    "https://www.theguardian.com/world/rss",
            "Al Jazeera":        "https://www.aljazeera.com/xml/rss/all.xml",
            "ABC News":          "https://abcnews.go.com/abcnews/topstories",
            "Google US Top":     "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
            # --- 中文 ---
            "Google CN Top":     "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            # "澎湃新闻":        "https://rsshub.app/thepaper/featured",
            # "央视新闻":        "https://rsshub.app/cctv/world",
        },
    },

    # ================================================================
    #  2. 科技新闻 (tech)
    #     AI、软件、硬件、互联网、科学
    # ================================================================
    "tech": {
        "name":  "科技新闻",
        "desc":  "AI、软件、硬件、互联网、前沿科技",
        "feeds": {
            # --- 英文 ---
            "TechCrunch":        "https://techcrunch.com/feed/",
            "The Verge":         "https://www.theverge.com/rss/index.xml",
            "Ars Technica":      "https://feeds.arstechnica.com/arstechnica/index",
            "Wired":             "https://www.wired.com/feed/rss",
            "Hacker News":       "https://hnrss.org/frontpage",
            "Engadget":          "https://www.engadget.com/rss.xml",
            "BBC Tech":          "http://feeds.bbci.co.uk/news/technology/rss.xml",
            "CNN Tech":          "http://rss.cnn.com/rss/edition_technology.rss",
            "Google US Tech":    "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
            # --- 中文 ---
            "Google CN Tech":    "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            # "36氪快讯":        "https://rsshub.app/36kr/newsflashes",
        },
    },

    # ================================================================
    #  3. 股市经济 (finance)
    #     股票、经济、商业、金融市场
    # ================================================================
    "finance": {
        "name":  "股市经济",
        "desc":  "股票市场、宏观经济、商业财经、金融动态",
        "feeds": {
            # --- 英文 ---
            "CNBC Top":          "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
            "MarketWatch":       "https://feeds.marketwatch.com/marketwatch/topstories/",
            "Yahoo Finance":     "https://finance.yahoo.com/news/rssindex",
            "Bloomberg":         "https://feeds.bloomberg.com/markets/news.rss",
            "Investing.com":     "https://www.investing.com/rss/news.rss",
            "BBC Business":      "http://feeds.bbci.co.uk/news/business/rss.xml",
            "CNN Money":         "http://rss.cnn.com/rss/money_news_international.rss",
            "Guardian Business": "https://www.theguardian.com/uk/business/rss",
            "FT":                "https://www.ft.com/rss/home",
            "Google US Finance": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
            # --- 中文 ---
            "Google CN Finance": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            # "华尔街见闻":      "https://rsshub.app/wallstreetcn/news/global",
        },
    },

    # ================================================================
    #  4. 美国移民 (immigration)
    #     签证、绿卡、H1B、移民政策、USCIS
    # ================================================================
    "immigration": {
        "name":  "美国移民",
        "desc":  "美国移民政策、签证绿卡、H1B、USCIS动态",
        "feeds": {
            # --- 英文 (Google News 关键词搜索) ---
            "Google Immigration":     "https://news.google.com/rss/search?q=US+immigration+policy&hl=en-US&gl=US&ceid=US:en",
            "Google USCIS":           "https://news.google.com/rss/search?q=USCIS+OR+green+card+OR+H1B+visa&hl=en-US&gl=US&ceid=US:en",
            "Google Deportation":     "https://news.google.com/rss/search?q=deportation+OR+ICE+immigration+enforcement&hl=en-US&gl=US&ceid=US:en",
            "Reuters Immigration":    "https://news.google.com/rss/search?q=site:reuters.com+immigration&hl=en-US&gl=US&ceid=US:en",
            # --- 中文 (Google News 关键词搜索) ---
            "Google 美国移民":         "https://news.google.com/rss/search?q=美国移民&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "Google 签证绿卡":         "https://news.google.com/rss/search?q=绿卡+OR+H1B+OR+签证+OR+移民局&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        },
    },

    # ================================================================
    #  [Agent 扩展模板] — 复制此模板添加新主题
    # ================================================================
    #  "your_topic_key": {
    #      "name":  "显示名称",
    #      "desc":  "主题描述 (用于 --list-topics 展示)",
    #      "feeds": {
    #          "Source Name":   "https://rss-url...",
    #          "Source Name 2": "https://rss-url-2...",
    #      },
    #  },

}

# ---------- 默认主题 ----------
# 不指定 --topics 时抓取哪些主题, 设为 ["all"] 表示全部
# Agent 可改为如 ["headlines", "tech"] 只默认抓这两个
DEFAULT_TOPICS = ["headlines", "tech", "finance"]
DISABLED_TOPICS = {"immigration"}

# ---------- 输出目录 ----------
# 默认: 项目根目录/news_raw/mmddyyyy-8pm
# 定时 runner 会用 --output 明确传入 8am 或 8pm 目录。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = str(PROJECT_ROOT / "news_raw" / f"{datetime.now().strftime('%m%d%Y')}-8pm")

# ---------- Ollama 设置 ----------
OLLAMA_MODEL    = "qwen3:8b"                    # Agent 可改为其他模型
OLLAMA_BASE_URL = "http://localhost:11434"       # Ollama 服务地址
OLLAMA_TIMEOUT  = 180                            # 单次请求超时(秒)
ARTICLE_TIMEOUT_BUFFER = 30                      # 单篇文章额外缓冲，避免整批被单个调用拖住

# ---------- 抓取设置 ----------
MAX_PER_FEED      = 10          # 每个 RSS 源最多取几条
FETCH_WORKERS     = 5           # 并发下载线程数
FETCH_TIMEOUT     = 30          # 单篇文章下载超时(秒)
MIN_ARTICLE_LEN   = 100         # 正文少于此字数则跳过
RECENT_HOURS      = 24          # 只保留 published/updated 在最近 N 小时内的 RSS 条目

# ---------- 总结 / 翻译设置 ----------
SUMMARY_FILENAME = "summary.md"  # 总结文件名
AI_WORKERS = 1
SUMMARY_PROMPT_TEMPLATE = """你是一位专业的新闻编辑。请阅读以下新闻全文，然后用 **简体中文** 写一份精华总结。

要求：
1. 总结控制在 150-300 字之间
2. 突出核心事件、关键人物、重要数据
3. 保持客观中立
4. 如果原文是英文，请翻译为简体中文后总结

新闻标题：{title}
新闻来源：{source}
发布时间：{date}

--- 新闻全文 ---
{content}
--- 全文结束 ---

请直接输出总结内容，不要加任何前缀或解释："""

TRANSLATION_PROMPT_TEMPLATE = """请将下面这篇新闻全文翻译成自然、准确、简体中文。

要求：
1. 忠实原文，不要编造
2. 保留关键信息、数字、人名、机构名
3. 不要总结，不要评论
4. 如果原文已经是中文，只原样轻微规范化后输出

新闻标题：{title}
新闻来源：{source}
发布时间：{date}

--- 新闻全文 ---
{content}
--- 全文结束 ---

请直接输出中文正文，不要加任何前缀或解释："""

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                       ===== 配置区结束 =====                        ║
# ╚══════════════════════════════════════════════════════════════════════╝

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("news_fetcher")


# ============================================================
#  工具函数
# ============================================================

def sanitize_filename(name, max_len=80):
    """将标题转为安全的文件名"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.replace('\n', ' ').replace('\r', '')
    if len(name) > max_len:
        name = name[:max_len].rsplit(' ', 1)[0]
    return name or "untitled"


def md5_short(text):
    """生成短 hash，用于去重/文件名唯一化"""
    return hashlib.md5(text.encode()).hexdigest()[:8]


def ensure_dir(path):
    """确保目录存在"""
    Path(path).mkdir(parents=True, exist_ok=True)


def entry_datetime(entry):
    """从 RSS entry 中解析 published/updated 时间；没有或无法解析则返回 None。"""
    for parsed_key in ("published_parsed", "updated_parsed"):
        parsed_value = entry.get(parsed_key)
        if parsed_value:
            return datetime.fromtimestamp(time.mktime(parsed_value), tz=timezone.utc)

    for text_key in ("published", "updated"):
        text_value = entry.get(text_key, "").strip()
        if not text_value:
            continue
        try:
            dt = parsedate_to_datetime(text_value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue

    return None


def is_recent_entry(entry, hours=RECENT_HOURS):
    """只接受最近 hours 小时内的 RSS 条目；无时间条目跳过。"""
    dt = entry_datetime(entry)
    if dt is None:
        return False
    return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)


def strip_html(text):
    """将 RSS 中的 HTML 摘要转成纯文本"""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ============================================================
#  主题解析
# ============================================================

def resolve_feeds(topic_keys):
    """根据主题 key 列表, 合并出最终的 {name: url} 字典"""
    if "all" in topic_keys:
        topic_keys = [k for k in TOPIC_FEEDS.keys() if k not in DISABLED_TOPICS]

    merged = {}
    active_topics = []
    for key in topic_keys:
        if key in DISABLED_TOPICS:
            log.info(f"  主题已禁用: '{key}', 跳过")
            continue
        if key not in TOPIC_FEEDS:
            log.warning(f"  未知主题: '{key}', 跳过 (用 --list-topics 查看可用主题)")
            continue
        topic = TOPIC_FEEDS[key]
        active_topics.append(f"{key} ({topic['name']})")
        for feed_name, feed_url in topic["feeds"].items():
            # 加上主题前缀, 方便在 summary.md 中按主题分组
            prefixed_name = f"[{topic['name']}] {feed_name}"
            merged[prefixed_name] = feed_url

    if active_topics:
        log.info(f"  激活主题: {', '.join(active_topics)}")
    return merged


# ============================================================
#  RSS 抓取
# ============================================================

def fetch_rss_entries(feed_name, feed_url, max_items):
    """解析单个 RSS 源，返回条目列表"""
    log.info(f"  正在解析 RSS: {feed_name} ...")
    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:
            log.warning(f"  RSS 解析异常 [{feed_name}]: {feed.bozo_exception}")
            return []

        entries = []
        for entry in feed.entries[:max_items]:
            if not is_recent_entry(entry):
                log.info(f"    跳过非最近{RECENT_HOURS}小时条目: {entry.get('title', '')[:50]}")
                continue
            raw_summary = entry.get("summary", "")
            if not raw_summary and entry.get("content"):
                first_content = entry.get("content", [{}])[0]
                raw_summary = first_content.get("value", "") if isinstance(first_content, dict) else ""
            entries.append({
                "source":    feed_name,
                "title":     entry.get("title", "").strip(),
                "link":      entry.get("link", ""),
                "published": entry.get("published", entry.get("updated", "")),
                "rss_summary": strip_html(raw_summary),
            })
        log.info(f"    {feed_name}: 获取 {len(entries)} 条")
        return entries

    except Exception as e:
        log.error(f"  RSS 获取失败 [{feed_name}]: {e}")
        return []


def fetch_all_rss(feeds, max_per_feed, total_limit=None):
    """从所有 RSS 源获取条目"""
    all_entries = []
    seen_links = set()

    for name, url in feeds.items():
        entries = fetch_rss_entries(name, url, max_per_feed)
        for e in entries:
            if e["link"] and e["link"] not in seen_links:
                seen_links.add(e["link"])
                all_entries.append(e)
                if total_limit and len(all_entries) >= total_limit:
                    log.info(f"\n  RSS 汇总: 共 {len(all_entries)} 条 (达到总条数上限 {total_limit})")
                    return all_entries

    log.info(f"\n  RSS 汇总: 共 {len(all_entries)} 条 (已去重)")
    return all_entries


# ============================================================
#  文章下载 (newspaper)
# ============================================================

def download_article(entry):
    """用 newspaper4k 下载并解析单篇文章"""
    url = entry["link"]
    try:
        article = Article(url, request_timeout=FETCH_TIMEOUT)
        article.download()
        article.parse()

        text = article.text.strip()
        if len(text) < MIN_ARTICLE_LEN:
            fallback_text = entry.get("rss_summary", "").strip()
            if len(fallback_text) >= max(60, MIN_ARTICLE_LEN // 2):
                log.info(f"  使用 RSS 摘要兜底: {entry['title'][:40]}")
                text = fallback_text
            else:
                log.warning(f"  正文过短({len(text)}字), 跳过: {entry['title'][:40]}")
                return None

        return {
            "source":    entry["source"],
            "title":     article.title or entry["title"],
            "link":      url,
            "published": entry["published"],
            "authors":   article.authors,
            "top_image": article.top_image or "",
            "text":      text,
        }

    except Exception as e:
        log.warning(f"  下载失败: {entry['title'][:40]}... | {e}")
        return None


def download_all_articles(entries, workers):
    """并发下载所有文章"""
    articles = []
    total = len(entries)
    log.info(f"\n  开始下载 {total} 篇文章 (并发={workers})...\n")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(download_article, e): e for e in entries}
        for i, future in enumerate(as_completed(future_map), 1):
            entry = future_map[future]
            result = future.result()
            status = "OK" if result else "FAIL"
            log.info(f"  [{i}/{total}] {status} {entry['title'][:50]}")
            if result:
                articles.append(result)

    log.info(f"\n  下载完成: 成功 {len(articles)}/{total} 篇\n")
    return articles


# ============================================================
#  保存为 Markdown
# ============================================================

def topic_key_from_source(source):
    m = re.match(r'^\[(.+?)\]\s*(.+)$', source)
    if not m:
        return 'other'
    topic_name = m.group(1)
    for key, meta in TOPIC_FEEDS.items():
        if meta['name'] == topic_name:
            return key
    return 'other'


def save_translation_md(article, output_dir, topic_key, filename):
    translated_dir = os.path.join(output_dir, topic_key, 'translated')
    ensure_dir(translated_dir)
    translated_path = os.path.join(translated_dir, filename)
    translated_text = article.get('translated_text', '') or '[翻译暂缺]'
    translated_content = f"""# {article['title']}｜中文翻译

| 字段 | 内容 |
|------|------|
| **来源** | {article['source']} |
| **发布时间** | {article['published']} |
| **原文链接** | [{article['link']}]({article['link']}) |

---

{translated_text}
"""
    with open(translated_path, 'w', encoding='utf-8') as f:
        f.write(translated_content)
    return translated_path


def save_article_md(article, output_dir):
    """将单篇文章保存为 .md 文件，返回文件路径"""
    safe_title = sanitize_filename(article["title"])
    short_hash = md5_short(article["link"])
    filename = f"{safe_title}_{short_hash}.md"
    topic_key = topic_key_from_source(article['source'])
    topic_dir = os.path.join(output_dir, topic_key)
    ensure_dir(topic_dir)
    filepath = os.path.join(topic_dir, filename)

    authors_str = ", ".join(article["authors"]) if article["authors"] else "Unknown"
    md_content = f"""# {article['title']}

| 字段 | 内容 |
|------|------|
| **来源** | {article['source']} |
| **作者** | {authors_str} |
| **发布时间** | {article['published']} |
| **原文链接** | [{article['link']}]({article['link']}) |

---

{article['text']}
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)

    save_translation_md(article, output_dir, topic_key, filename)
    return filepath


def save_all_articles(articles, output_dir):
    """保存所有文章，返回带 filepath 的列表"""
    ensure_dir(output_dir)
    saved = []
    for art in articles:
        try:
            fp = save_article_md(art, output_dir)
            art["filepath"] = fp
            art["relpath"] = os.path.relpath(fp, output_dir)
            saved.append(art)
        except Exception as e:
            log.error(f"  保存失败: {art['title'][:40]}... | {e}")

    log.info(f"  已保存 {len(saved)} 篇文章到: {output_dir}")
    return saved


# ============================================================
#  Ollama 本地模型总结
# ============================================================

def check_ollama():
    """检查 Ollama 服务是否可用"""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def ollama_generate(prompt, num_predict=1024, temperature=0.3, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": num_predict,
                    },
                },
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "").strip()
            return re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait_s = 3 * (attempt + 1)
                log.warning(f"  Ollama 调用失败，{wait_s}s 后重试 ({attempt + 1}/{retries}) | {e}")
                time.sleep(wait_s)
            else:
                raise last_err


def ollama_summarize(article):
    """调用 Ollama 对单篇文章生成中文总结"""
    content = article["text"]
    if len(content) > 8000:
        content = content[:8000] + "\n\n[...正文过长, 已截断...]"
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        title=article["title"],
        source=article["source"],
        date=article["published"],
        content=content,
    )
    try:
        summary = ollama_generate(prompt, num_predict=1024, temperature=0.3)
        return summary if summary else "[总结生成为空]"
    except requests.exceptions.Timeout:
        return "[错误: Ollama 请求超时]"
    except Exception as e:
        return f"[错误: {e}]"


def ollama_translate(article):
    content = article['text']
    if len(content) > 8000:
        content = content[:8000] + "\n\n[...正文过长, 已截断...]"
    prompt = TRANSLATION_PROMPT_TEMPLATE.format(
        title=article['title'],
        source=article['source'],
        date=article['published'],
        content=content,
    )
    try:
        translated = ollama_generate(prompt, num_predict=2200, temperature=0.1)
        return translated if translated else "[翻译生成为空]"
    except requests.exceptions.Timeout:
        return "[错误: Ollama 翻译请求超时]"
    except Exception as e:
        return f"[错误: {e}]"


def summarize_and_translate_all(articles):
    """为所有文章生成总结和中文翻译。

    这里刻意牺牲一些并发，换取更强的确定性：
    - 不再对单篇文章同时发起 summary + translation 两个 Ollama 请求
    - 每篇文章按“先总结、后翻译”顺序执行
    - 任一步失败都记录错误并继续，不让整批任务被单篇卡死
    """
    total = len(articles)
    per_call_timeout = OLLAMA_TIMEOUT
    log.info(f"\n  开始使用 Ollama ({OLLAMA_MODEL}) 生成总结 + 中文翻译...\n")
    log.info(f"  单次 Ollama 超时: {per_call_timeout}s | AI_WORKERS: {AI_WORKERS}")

    def process_article(payload):
        idx, art = payload
        title_short = art['title'][:50]
        log.info(f"  [{idx}/{total}] 启动: {title_short}...")
        t0 = time.time()

        try:
            summary = ollama_summarize(art)
        except Exception as e:
            log.warning(f"  [{idx}/{total}] 总结失败: {title_short} | {e}")
            summary = f"[错误: 总结失败或超时: {e}]"

        try:
            translated = ollama_translate(art)
        except Exception as e:
            log.warning(f"  [{idx}/{total}] 翻译失败: {title_short} | {e}")
            translated = "[翻译暂缺]"

        elapsed = time.time() - t0
        return idx, art, summary, translated, elapsed

    results = []
    pool = ThreadPoolExecutor(max_workers=AI_WORKERS)
    try:
        future_map = {
            pool.submit(process_article, (i, art)): i for i, art in enumerate(articles, 1)
        }
        for future in as_completed(future_map):
            idx, art, summary, translated, elapsed = future.result()
            art['translated_text'] = translated
            log.info(f"  [{idx}/{total}] 完成总结+翻译 ({elapsed:.1f}s): {art['title'][:50]}")
            results.append({
                "title": art["title"],
                "source": art["source"],
                "published": art["published"],
                "link": art["link"],
                "filepath": art.get("filepath", ""),
                "summary": summary,
            })
    finally:
        pool.shutdown(wait=True, cancel_futures=False)

    results.sort(key=lambda x: x['filepath'])
    return results


# ============================================================
#  生成 summary.md (按主题分组)
# ============================================================

def generate_summary_md(summaries, output_dir, active_topics=None):
    """生成汇总 summary.md, 按主题分组"""
    ensure_dir(output_dir)
    filepath = os.path.join(output_dir, SUMMARY_FILENAME)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 构建主题显示
    if active_topics and "all" not in active_topics:
        topics_str = ", ".join(active_topics)
    else:
        topics_str = "全部主题"

    lines = [
        f"# 每日新闻总结",
        f"",
        f"> **生成时间**: {now_str}  ",
        f"> **使用模型**: {OLLAMA_MODEL}  ",
        f"> **抓取主题**: {topics_str}  ",
        f"> **文章数量**: {len(summaries)} 篇  ",
        f"",
        f"---",
        f"",
    ]

    # 按主题前缀分组:  source 格式为 "[头条新闻] BBC Top"
    topic_groups = {}  # { "头条新闻": [items...] }
    for s in summaries:
        src = s["source"]
        # 提取 [主题名] 前缀
        m = re.match(r'^\[(.+?)\]\s*(.+)$', src)
        if m:
            topic_name = m.group(1)
            feed_name  = m.group(2)
        else:
            topic_name = "其他"
            feed_name  = src
        s["_feed_name"] = feed_name
        topic_groups.setdefault(topic_name, []).append(s)

    for topic_name, items in topic_groups.items():
        lines.append(f"## {topic_name}")
        lines.append("")

        for item in items:
            md_filename = item["filepath"] if item["filepath"] else ""
            lines.append(f"### {item['title']}")
            lines.append("")
            lines.append(f"- **来源**: {item['_feed_name']}")
            lines.append(f"- **时间**: {item['published']}")
            lines.append("")
            lines.append(f"{item['summary']}")
            lines.append("")
            lines.append("---")
            lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info(f"\n  总结文件已生成: {filepath}")
    return filepath


# ============================================================
#  从已有 .md 文件重建文章列表 (用于 --summary-only)
# ============================================================

def load_articles_from_dir(output_dir):
    """读取目录中已有的 .md 文件，解析为文章列表"""
    articles = []
    md_dir = Path(output_dir)
    if not md_dir.exists():
        log.error(f"  目录不存在: {output_dir}")
        return []

    for md_file in sorted(md_dir.glob("*.md")):
        if md_file.name == SUMMARY_FILENAME:
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            # 解析标题 (第一行 # 开头)
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else md_file.stem

            # 解析来源
            source_match = re.search(r'\*\*来源\*\*\s*\|\s*(.+)', content)
            source = source_match.group(1).strip() if source_match else "Unknown"

            # 解析时间
            date_match = re.search(r'\*\*发布时间\*\*\s*\|\s*(.+)', content)
            published = date_match.group(1).strip() if date_match else ""

            # 解析链接
            link_match = re.search(r'\*\*原文链接\*\*\s*\|\s*\[(.+?)\]', content)
            link = link_match.group(1).strip() if link_match else ""

            # 提取正文 (--- 分隔符之后)
            parts = content.split("---", 2)
            text = parts[2].strip() if len(parts) >= 3 else content

            articles.append({
                "title":     title,
                "source":    source,
                "published": published,
                "link":      link,
                "text":      text,
                "filepath":  str(md_file),
            })
        except Exception as e:
            log.warning(f"  解析失败: {md_file.name} | {e}")

    log.info(f"  从目录加载了 {len(articles)} 篇文章")
    return articles


# ============================================================
#  主流程
# ============================================================

def list_topics():
    """打印所有可用主题及其 RSS 源"""
    print("\n" + "=" * 65)
    print("  可用主题列表 (--topics 参数可用的值)")
    print("=" * 65)
    for key, topic in TOPIC_FEEDS.items():
        feed_count = len(topic["feeds"])
        print(f"\n  {key:<20} {topic['name']}")
        print(f"  {'':20} {topic['desc']}")
        print(f"  {'':20} RSS 源数: {feed_count}")
        for fname, furl in topic["feeds"].items():
            short_url = furl[:60] + "..." if len(furl) > 60 else furl
            print(f"  {'':22} - {fname:<25} {short_url}")
    print("\n" + "=" * 65)
    print(f"  默认主题: {', '.join(DEFAULT_TOPICS)}")
    print(f"  用法示例: python3 rss_news_fetcher.py --topics {list(TOPIC_FEEDS.keys())[0]}")
    print("=" * 65 + "\n")


def parse_args():
    topic_keys = list(TOPIC_FEEDS.keys())
    parser = argparse.ArgumentParser(
        description="RSS News Fetcher & Summarizer (Topic-based, Ollama)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"可用主题: {', '.join(topic_keys)}, all\n"
               f"示例: python3 rss_news_fetcher.py --topics tech finance --max 5"
    )
    parser.add_argument(
        "--topics", nargs="+", default=None,
        metavar="TOPIC",
        help=f"选择抓取的主题 (可多选, 空格分隔; 'all'=全部). "
             f"可用: {', '.join(topic_keys)}, all. "
             f"默认: {', '.join(DEFAULT_TOPICS)}"
    )
    parser.add_argument(
        "--list-topics", action="store_true",
        help="列出所有可用主题及其 RSS 源, 然后退出"
    )
    parser.add_argument(
        "--max", type=int, default=MAX_PER_FEED,
        help=f"每个 RSS 源最多抓取条数 (默认 {MAX_PER_FEED})"
    )
    parser.add_argument(
        "--total-limit", type=int, default=None,
        help="所有 RSS 源合并后，raw 新闻总条数上限（可用于快速测试）"
    )
    parser.add_argument(
        "--feeds-only", action="store_true",
        help="仅抓取文章保存, 不进行总结"
    )
    parser.add_argument(
        "--summary-only", action="store_true",
        help="仅对 OUTPUT_DIR 中已有的 .md 文件做总结"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help=f"自定义输出目录 (默认 {OUTPUT_DIR})"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help=f"Ollama 模型名 (默认 {OLLAMA_MODEL})"
    )
    return parser.parse_args()


def main():
    global OUTPUT_DIR, OLLAMA_MODEL, MAX_PER_FEED

    args = parse_args()

    # --list-topics: 展示后退出
    if args.list_topics:
        list_topics()
        sys.exit(0)

    # 确定主题
    active_topics = args.topics if args.topics else DEFAULT_TOPICS

    # 命令行参数覆盖配置
    if args.model:
        OLLAMA_MODEL = args.model
    MAX_PER_FEED = args.max

    # 合并 RSS 源
    RSS_FEEDS = resolve_feeds(active_topics)
    if not RSS_FEEDS and not args.summary_only:
        log.error("没有匹配到任何 RSS 源, 请检查 --topics 参数。")
        sys.exit(1)

    # 输出目录: 单主题时自动加后缀
    if args.output:
        OUTPUT_DIR = os.path.expanduser(args.output)
    elif len(active_topics) == 1 and active_topics[0] != "all":
        OUTPUT_DIR = str(
            PROJECT_ROOT / "news_raw" / f"{datetime.now().strftime('%m%d%Y')}_news_{active_topics[0]}"
        )

    log.info("=" * 60)
    log.info("  RSS News Fetcher & Summarizer")
    log.info("=" * 60)
    log.info(f"  主题:      {', '.join(active_topics)}")
    log.info(f"  输出目录:  {OUTPUT_DIR}")
    log.info(f"  Ollama:    {OLLAMA_MODEL}")
    log.info(f"  每源条数:  {MAX_PER_FEED}")
    log.info(f"  RSS 源数:  {len(RSS_FEEDS)}")
    log.info("=" * 60)

    # ------ 阶段1: 获取文章 ------
    if args.summary_only:
        articles = load_articles_from_dir(OUTPUT_DIR)
        if not articles:
            log.error("没有找到可总结的文章, 退出。")
            sys.exit(1)
    else:
        # 1a. 解析 RSS
        entries = fetch_all_rss(RSS_FEEDS, MAX_PER_FEED, args.total_limit)
        if not entries:
            log.error("没有获取到任何 RSS 条目, 退出。")
            sys.exit(1)

        # 1b. 下载全文
        articles = download_all_articles(entries, FETCH_WORKERS)
        if not articles:
            log.error("没有成功下载任何文章, 退出。")
            sys.exit(1)

        # 1c. 保存 Markdown
        articles = save_all_articles(articles, OUTPUT_DIR)

    # ------ 阶段2: AI 总结 ------
    if args.feeds_only:
        log.info("\n  仅抓取模式, 跳过总结。完成！")
        return

    # 检查 Ollama
    if not check_ollama():
        log.error(
            f"  无法连接 Ollama ({OLLAMA_BASE_URL})。\n"
            f"   请确保 Ollama 正在运行: ollama serve\n"
            f"   已保存的文章不受影响, 之后可用 --summary-only 重新生成总结。"
        )
        sys.exit(1)

    # 并行生成总结 + 中文翻译
    summaries = summarize_and_translate_all(articles)

    # 翻译结果写回文章 markdown
    articles = save_all_articles(articles, OUTPUT_DIR)

    # 生成 summary.md
    summary_path = generate_summary_md(summaries, OUTPUT_DIR, active_topics)

    # ------ 完成 ------
    log.info("\n" + "=" * 60)
    log.info("  全部完成！")
    log.info(f"   抓取主题:  {', '.join(active_topics)}")
    log.info(f"   文章目录:  {OUTPUT_DIR}")
    log.info(f"   文章数量:  {len(articles)} 篇")
    log.info(f"   总结文件:  {summary_path}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
