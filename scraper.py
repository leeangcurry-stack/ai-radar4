"""
scraper.py — AI Radar RSS 爬虫
爬取公开 RSS Feed，按关键词过滤，输出结构化 JSON
无需任何 API Key，完全免费
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from html import unescape

# ── RSS 信源配置 ──────────────────────────────────────────────────────────
FEEDS = [
    # 海外官方博客
    {"name": "OpenAI Blog",      "url": "https://openai.com/blog/rss.xml",                     "type": "official", "region": "overseas"},
    {"name": "Anthropic News",   "url": "https://www.anthropic.com/rss.xml",                   "type": "official", "region": "overseas"},
    {"name": "Google DeepMind",  "url": "https://deepmind.google/blog/rss/",                   "type": "official", "region": "overseas"},
    {"name": "Meta AI",          "url": "https://ai.meta.com/blog/feed/",                      "type": "official", "region": "overseas"},
    # 海外科技媒体
    {"name": "TechCrunch AI",    "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "type": "media", "region": "overseas"},
    {"name": "The Verge AI",     "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "type": "media", "region": "overseas"},
    {"name": "VentureBeat AI",   "url": "https://venturebeat.com/category/ai/feed/",           "type": "media", "region": "overseas"},
    {"name": "Wired AI",         "url": "https://www.wired.com/feed/tag/ai/latest/rss",        "type": "media", "region": "overseas"},
    {"name": "MIT Tech Review",  "url": "https://www.technologyreview.com/feed/",              "type": "media", "region": "overseas"},
    # 开发者社区
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml",                "type": "dev",    "region": "overseas"},
    {"name": "arxiv cs.AI",      "url": "https://rss.arxiv.org/rss/cs.AI",                    "type": "paper",  "region": "overseas"},
    # 国内媒体
    {"name": "机器之心",          "url": "https://www.jiqizhixin.com/rss",                      "type": "media",  "region": "china"},
    {"name": "量子位",            "url": "https://www.qbitai.com/feed",                         "type": "media",  "region": "china"},
    {"name": "36Kr AI",          "url": "https://36kr.com/feed",                               "type": "media",  "region": "china"},
]

# ── 关键词过滤 ────────────────────────────────────────────────────────────
KEYWORDS_HIGH = [
    # 模型发布
    "GPT", "Claude", "Gemini", "Grok", "DeepSeek", "Qwen", "LLaMA", "Llama",
    "release", "launch", "发布", "推出", "上线",
    # 重大产品
    "Agent", "AGI", "o1", "o3", "Sora", "Codex",
    # 融资
    "funding", "raises", "billion", "valuation", "融资", "估值", "亿",
    # 芯片
    "Nvidia", "GPU", "TPU", "NPU", "Ascend", "昇腾",
]

KEYWORDS_MID = [
    "AI", "LLM", "model", "benchmark", "fine-tun", "multimodal",
    "inference", "training", "open source", "开源",
    "OpenAI", "Anthropic", "Google", "Meta", "Microsoft", "xAI",
    "字节", "阿里", "百度", "华为", "腾讯", "月之暗面", "智谱",
    "MCP", "RAG", "RLHF", "transformer",
]

EXCLUDE_KEYWORDS = [
    "cookie", "privacy policy", "subscribe", "newsletter",
    "podcast", "webinar", "job", "hiring", "career",
]

# ── 时间范围：过去 14 天 ──────────────────────────────────────────────────
CUTOFF = datetime.now(timezone.utc) - timedelta(days=14)

# ── 分类规则 ─────────────────────────────────────────────────────────────
def classify(title: str, desc: str) -> str:
    text = (title + " " + desc).lower()
    if any(k.lower() in text for k in ["funding", "raises", "billion", "valuation", "融资", "估值", "投资"]):
        return "funding"
    if any(k.lower() in text for k in ["chip", "gpu", "tpu", "npu", "ascend", "昇腾", "算力", "infrastructure", "mcp"]):
        return "infra"
    if any(k in text for k in ["字节", "阿里", "百度", "华为", "腾讯", "月之暗面", "智谱", "deepseek", "qwen", "文心", "通义", "混元"]):
        return "china"
    if any(k.lower() in text for k in ["release", "launch", "model", "gpt", "claude", "gemini", "llama", "发布", "推出", "版本"]):
        return "model"
    return "product"


def impact_score(title: str, desc: str) -> str:
    text = (title + " " + desc).lower()
    high_hits = sum(1 for k in KEYWORDS_HIGH if k.lower() in text)
    if high_hits >= 3:
        return "high"
    if high_hits >= 1:
        return "mid"
    return "low"


# ── HTTP 请求（带 UA 和超时）─────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AIRadarBot/1.0; +https://github.com/ai-radar)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def fetch_feed(feed: dict) -> list[dict]:
    url = feed["url"]
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except URLError as e:
        print(f"  [跳过] {feed['name']}: {e}")
        return []
    except Exception as e:
        print(f"  [跳过] {feed['name']}: {e}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  [解析失败] {feed['name']}: {e}")
        return []

    # 兼容 RSS 2.0 和 Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//atom:entry", ns)

    results = []
    for item in items:
        def get(tag, atom_tag=None):
            el = item.find(tag)
            if el is None and atom_tag:
                el = item.find(atom_tag, ns)
            return (el.text or "").strip() if el is not None and el.text else ""

        title   = unescape(get("title", "atom:title"))
        link    = get("link", "atom:link")
        desc    = unescape(re.sub(r"<[^>]+>", " ", get("description") or get("summary", "atom:summary")))
        pub_raw = get("pubDate") or get("published", "atom:published") or get("updated", "atom:updated")

        # 如果 link 是 Atom <link href="...">
        if not link:
            el = item.find("atom:link", ns)
            if el is not None:
                link = el.get("href", "")

        if not title:
            continue

        # 解析时间
        pub_dt = parse_date(pub_raw)

        # 过滤时间范围
        if pub_dt and pub_dt < CUTOFF:
            continue

        # 关键词过滤
        combined = title + " " + desc
        if any(k.lower() in combined.lower() for k in EXCLUDE_KEYWORDS):
            continue
        if not any(k.lower() in combined.lower() for k in KEYWORDS_HIGH + KEYWORDS_MID):
            continue

        results.append({
            "title":   title[:120],
            "desc":    desc[:200].strip(),
            "link":    link,
            "source":  feed["name"],
            "region":  feed["region"],
            "date":    pub_dt.strftime("%Y-%m-%d") if pub_dt else "",
            "type":    classify(title, desc),
            "impact":  impact_score(title, desc),
            "hot":     impact_score(title, desc) == "high",
        })

    print(f"  [OK] {feed['name']}: {len(results)} 条")
    return results


def parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ── 去重（按标题相似度）─────────────────────────────────────────────────
def dedup(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        key = re.sub(r"\W+", "", item["title"].lower())[:40]
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# ── 生成趋势摘要（基于词频）─────────────────────────────────────────────
TREND_TOPICS = [
    ("Agent应用", ["agent", "agentic", "autonomous", "自主", "workflow"]),
    ("模型竞争", ["release", "launch", "benchmark", "sota", "发布", "超越"]),
    ("推理成本", ["price", "cost", "cheap", "token", "pricing", "定价", "降价"]),
    ("开源生态", ["open source", "open-source", "opensource", "开源", "llama", "deepseek"]),
    ("多模态",   ["multimodal", "vision", "image", "video", "audio", "多模态", "图像"]),
    ("国产AI",   ["字节", "阿里", "百度", "华为", "deepseek", "qwen", "月之暗面", "智谱"]),
    ("AI安全",   ["safety", "alignment", "risk", "regulation", "安全", "监管", "合规"]),
    ("企业落地", ["enterprise", "b2b", "deploy", "production", "企业", "落地", "商用"]),
]

def build_trends(items: list[dict]) -> list[dict]:
    all_text = " ".join(i["title"] + " " + i["desc"] for i in items).lower()
    scored = []
    for label, kws in TREND_TOPICS:
        count = sum(all_text.count(k.lower()) for k in kws)
        scored.append((count, label, kws))
    scored.sort(reverse=True)

    trends = []
    for count, label, kws in scored[:5]:
        if count == 0:
            continue
        related = [i for i in items if any(k.lower() in (i["title"] + i["desc"]).lower() for k in kws)][:3]
        examples = "、".join(r["title"][:25] for r in related)
        trends.append({
            "title": label,
            "body":  f"本周相关报道 {count} 次，代表事件：{examples}。" if examples else f"本周出现 {count} 次相关报道。",
            "verdict": f"持续关注{label}方向的产品落地与竞争格局变化。"
        })
    return trends


# ── 主流程 ────────────────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print(f"AI Radar 爬虫启动 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    all_items = []
    for feed in FEEDS:
        print(f"爬取: {feed['name']}")
        items = fetch_feed(feed)
        all_items.extend(items)
        time.sleep(1)  # 礼貌性间隔

    print(f"\n原始条目: {len(all_items)}")
    all_items = dedup(all_items)
    print(f"去重后: {len(all_items)}")

    # 按时间排序（最新在前）
    all_items.sort(key=lambda x: x["date"], reverse=True)

    # 取前 30 条
    events = all_items[:30]

    # 统计
    high_impact = [e for e in events if e["impact"] == "high"]
    top_story   = high_impact[0] if high_impact else (events[0] if events else {})
    funding     = [e for e in events if e["type"] == "funding"]
    funding_str = f"{len(funding)} 起" if funding else "—"

    trends = build_trends(events)

    now = datetime.now()
    data = {
        "generated_at": now.strftime("%Y年%m月%d日"),
        "generated_ts": now.isoformat(),
        "summary": f"本周共追踪到 {len(events)} 条AI动态，覆盖海外及国内主要信源。"
                   f"{'高影响事件 ' + str(len(high_impact)) + ' 条，' if high_impact else ''}"
                   f"重点关注：{events[0]['title'][:30] if events else '暂无'}等。",
        "top_story": {
            "title":  top_story.get("title", ""),
            "desc":   top_story.get("desc", ""),
            "source": top_story.get("source", ""),
            "date":   top_story.get("date", ""),
            "link":   top_story.get("link", ""),
        },
        "metrics": {
            "events_count":  len(events),
            "sources_count": len(FEEDS),
            "funding_total": funding_str,
        },
        "events": events,
        "trends": trends,
    }

    out = Path("docs") / "data.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 数据已保存至 {out}（{len(events)} 条事件）")
    print("=" * 50)


if __name__ == "__main__":
    main()
