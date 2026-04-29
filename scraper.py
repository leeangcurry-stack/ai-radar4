"""
scraper.py — AI Radar · Google News RSS 版
通过 Google News RSS 查询关键词，覆盖全球所有主流媒体
无需 API Key，GitHub Actions 环境完全可用
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


QUERIES = [
    # 海外 · 英文
    {"name": "OpenAI 动态",      "url": "https://news.google.com/rss/search?q=OpenAI+GPT&hl=en-US&gl=US&ceid=US:en",                              "region": "overseas"},
    {"name": "Anthropic Claude", "url": "https://news.google.com/rss/search?q=Anthropic+Claude+AI&hl=en-US&gl=US&ceid=US:en",                     "region": "overseas"},
    {"name": "Google AI",        "url": "https://news.google.com/rss/search?q=Google+Gemini+DeepMind&hl=en-US&gl=US&ceid=US:en",                  "region": "overseas"},
    {"name": "AI 模型发布",       "url": "https://news.google.com/rss/search?q=AI+model+release+LLM&hl=en-US&gl=US&ceid=US:en",                    "region": "overseas"},
    {"name": "AI 融资",           "url": "https://news.google.com/rss/search?q=AI+startup+funding+raises+billion&hl=en-US&gl=US&ceid=US:en",       "region": "overseas"},
    {"name": "AI Agent 产品",     "url": "https://news.google.com/rss/search?q=AI+agent+product+launch&hl=en-US&gl=US&ceid=US:en",                 "region": "overseas"},
    {"name": "xAI Grok",         "url": "https://news.google.com/rss/search?q=xAI+Grok+Elon+Musk+AI&hl=en-US&gl=US&ceid=US:en",                  "region": "overseas"},
    {"name": "Meta AI Llama",    "url": "https://news.google.com/rss/search?q=Meta+AI+Llama+open+source&hl=en-US&gl=US&ceid=US:en",               "region": "overseas"},
    {"name": "AI 芯片",           "url": "https://news.google.com/rss/search?q=Nvidia+AI+chip+GPU+inference&hl=en-US&gl=US&ceid=US:en",            "region": "overseas"},
    # 国内 · 中文
    {"name": "DeepSeek",         "url": "https://news.google.com/rss/search?q=DeepSeek&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",                                        "region": "china"},
    {"name": "国内大模型",         "url": "https://news.google.com/rss/search?q=%E5%A4%A7%E6%A8%A1%E5%9E%8B+%E5%8F%91%E5%B8%83+AI&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",   "region": "china"},
    {"name": "字节豆包",           "url": "https://news.google.com/rss/search?q=%E5%AD%97%E8%8A%82%E8%B7%B3%E5%8A%A8+%E8%B1%86%E5%8C%85+AI&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "region": "china"},
    {"name": "阿里通义",           "url": "https://news.google.com/rss/search?q=%E9%98%BF%E9%87%8C+%E9%80%9A%E4%B9%89+AI+%E5%A4%A7%E6%A8%A1%E5%9E%8B&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "region": "china"},
    {"name": "百度文心",           "url": "https://news.google.com/rss/search?q=%E7%99%BE%E5%BA%A6+%E6%96%87%E5%BF%83+AI&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",          "region": "china"},
    {"name": "华为昇腾",           "url": "https://news.google.com/rss/search?q=%E5%8D%8E%E4%B8%BA+%E6%98%87%E8%85%BE+AI+%E8%8A%AF%E7%89%87&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "region": "china"},
    {"name": "月之暗面Kimi",       "url": "https://news.google.com/rss/search?q=%E6%9C%88%E4%B9%8B%E6%9A%97%E9%9D%A2+Kimi+AI&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",     "region": "china"},
    {"name": "国内AI融资",         "url": "https://news.google.com/rss/search?q=AI+%E8%9E%8D%E8%B5%84+%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+%E4%BA%BF&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "region": "china"},
]

BLOCKED_DOMAINS = {
    "arxiv.org", "reddit.com", "youtube.com", "twitter.com", "x.com",
    "linkedin.com", "pinterest.com", "instagram.com", "facebook.com",
}

NOISE_WORDS = [
    "subscribe", "newsletter", "podcast", "webinar",
    "job opening", "privacy policy", "terms of service",
]


def classify(title: str, desc: str, query_name: str) -> str:
    text = (title + " " + desc + " " + query_name).lower()
    if any(k in text for k in ["融资", "funding", "raises", "billion", "valuation", "估值", "投资", "round"]):
        return "funding"
    if any(k in text for k in ["chip", "gpu", "tpu", "npu", "昇腾", "算力", "ascend", "nvidia", "芯片", "mcp", "infrastructure"]):
        return "infra"
    if any(k in text for k in ["deepseek", "字节", "阿里", "百度", "华为", "腾讯", "月之暗面", "智谱", "qwen", "文心", "通义", "混元", "豆包", "kimi"]):
        return "china"
    if any(k in text for k in ["release", "launch", "model", "gpt", "claude", "gemini", "llama", "发布", "推出", "版本", "update"]):
        return "model"
    return "product"


def impact_score(title: str, desc: str) -> str:
    text = (title + " " + desc).lower()
    high = ["billion", "gpt-5", "claude", "gemini", "deepseek", "llama", "acquisition", "ipo", "breakthrough", "收购", "发布", "亿", "百亿"]
    mid  = ["million", "raises", "launch", "release", "announce", "open source", "partnership", "推出", "合作", "开源"]
    if sum(1 for k in high if k in text) >= 2:
        return "high"
    if any(k in text for k in high):
        return "mid"
    if any(k in text for k in mid):
        return "mid"
    return "low"


def extract_domain(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/?#]+)", url)
    return m.group(1) if m else ""


def parse_date(raw: str):
    if not raw:
        return None
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}

CUTOFF = datetime.now(timezone.utc) - timedelta(days=7)


def fetch_query(q: dict) -> list[dict]:
    try:
        # 对URL中的中文关键词做编码，避免部分环境下请求失败
        from urllib.parse import quote, urlparse, urlunparse, urlencode, parse_qs
        parsed = urlparse(q["url"])
        qs = parse_qs(parsed.query, keep_blank_values=True)
        # 重新编码query参数（parse_qs已解码，urlencode重新编码）
        encoded_query = urlencode({k: v[0] for k, v in qs.items()})
        safe_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path,
                               parsed.params, encoded_query, parsed.fragment))
        req = Request(safe_url, headers=HEADERS)
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"  [跳过] {q['name']}: {e}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  [解析失败] {q['name']}: {e}")
        return []

    results = []
    for item in root.findall(".//item"):
        def get(tag):
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        title   = unescape(get("title"))
        link    = get("link") or get("guid")
        desc    = unescape(re.sub(r"<[^>]+>", " ", get("description")))
        pub_raw = get("pubDate")

        # source 元素
        src_el  = item.find("source")
        src_name   = src_el.text.strip() if src_el is not None and src_el.text else q["name"]
        src_url    = src_el.get("url", "") if src_el is not None else ""
        src_domain = extract_domain(src_url) if src_url else extract_domain(link)

        if not title:
            continue
        if src_domain in BLOCKED_DOMAINS:
            continue

        combined = (title + " " + desc).lower()
        if any(w in combined for w in NOISE_WORDS):
            continue

        pub_dt = parse_date(pub_raw)
        if pub_dt and pub_dt < CUTOFF:
            continue

        results.append({
            "title":  title[:150],
            "desc":   desc[:250].strip(),
            "link":   link,
            "source": src_name,
            "region": q["region"],
            "date":   pub_dt.strftime("%Y-%m-%d") if pub_dt else "",
            "type":   classify(title, desc, q["name"]),
            "impact": impact_score(title, desc),
            "hot":    impact_score(title, desc) == "high",
        })

    print(f"  [OK] {q['name']}: {len(results)} 条  (来自 {len(set(r['source'] for r in results))} 个媒体)")
    return results


def dedup(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for item in items:
        key = re.sub(r"\W+", "", item["title"].lower())[:40]
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


TREND_TOPICS = [
    ("Agent应用",  ["agent", "agentic", "autonomous", "自主", "workflow"]),
    ("模型竞争",   ["release", "launch", "benchmark", "sota", "发布", "超越"]),
    ("推理成本",   ["price", "cost", "cheap", "token", "pricing", "定价", "降价"]),
    ("开源生态",   ["open source", "open-source", "开源", "llama", "deepseek"]),
    ("多模态",     ["multimodal", "vision", "video", "audio", "多模态"]),
    ("国产AI",     ["字节", "阿里", "百度", "华为", "deepseek", "qwen", "月之暗面"]),
    ("AI治理",     ["safety", "regulation", "安全", "监管", "governance"]),
    ("企业落地",   ["enterprise", "deploy", "production", "企业", "落地"]),
]

def build_trends(items: list[dict]) -> list[dict]:
    # 按"命中该话题关键词的新闻条数"计算，而非字符频次（避免重复命中导致数值相同）
    scored = []
    for label, kws in TREND_TOPICS:
        matched = [i for i in items
                   if any(k.lower() in (i["title"] + " " + i["desc"]).lower() for k in kws)]
        scored.append((len(matched), label, matched))
    scored.sort(key=lambda x: x[0], reverse=True)

    trends = []
    seen_items = set()  # 避免同一条新闻在多个趋势里重复出现
    for count, label, matched in scored[:5]:
        if count == 0:
            continue
        # 取未被其他趋势用过的新闻作为代表事件
        fresh = [i for i in matched if i["title"] not in seen_items][:3]
        if not fresh:
            fresh = matched[:3]
        for i in fresh:
            seen_items.add(i["title"])
        examples = "；".join(r["title"][:40] for r in fresh)
        body = f"本周 {count} 条相关报道。代表：{examples}。" if examples else f"本周 {count} 条相关报道。"
        trends.append({
            "title": label,
            "body":  body,
        })
    return trends


def main():
    print("=" * 52)
    print(f"AI Radar 启动 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据源：Google News RSS · {len(QUERIES)} 个查询")
    print("=" * 52)

    all_items = []
    for q in QUERIES:
        print(f"查询: {q['name']}")
        all_items.extend(fetch_query(q))
        time.sleep(1.5)

    print(f"\n原始条目: {len(all_items)}")
    all_items = dedup(all_items)
    print(f"去重后:   {len(all_items)}")

    # 国内内容：每个查询最多贡献2条（避免单一话题霸屏），总计取前10条
    china_items = [i for i in all_items if i["region"] == "china"]
    china_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    china_quota = []
    china_query_count = {}
    for item in china_items:
        q = item.get("_query", "")
        if china_query_count.get(q, 0) < 2:
            china_quota.append(item)
            china_query_count[q] = china_query_count.get(q, 0) + 1
        if len(china_quota) >= 10:
            break

    # 海外内容：取前25条
    overseas_items = [i for i in all_items if i["region"] != "china"]
    overseas_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    overseas_quota = overseas_items[:30]

    # 合并后按时间排序
    events = china_quota + overseas_quota
    events.sort(key=lambda x: x.get("date", ""), reverse=True)

    high_items    = [e for e in events if e["impact"] == "high"]
    china_count   = len([e for e in events if e["region"] == "china"])
    overseas_count = len([e for e in events if e["region"] != "china"])
    funding_count = len([e for e in events if e["type"] == "funding"])
    top_story     = high_items[0] if high_items else (events[0] if events else {})
    print(f"      国内: {china_count} 条 / 海外: {overseas_count} 条")

    now  = datetime.now()
    data = {
        "generated_at": now.strftime("%Y年%m月%d日"),
        "generated_ts": now.isoformat(),
        "summary": (
            f"本周追踪到 {len(events)} 条AI动态，"
            f"海外 {len(events)-china_count} 条、国内 {china_count} 条。"
            + (f"高影响事件 {len(high_items)} 条。" if high_items else "")
            + (f"融资事件 {funding_count} 起。" if funding_count else "")
        ),
        "top_story": {
            "title":  top_story.get("title", ""),
            "desc":   top_story.get("desc", ""),
            "source": top_story.get("source", ""),
            "date":   top_story.get("date", ""),
            "link":   top_story.get("link", ""),
        },
        "metrics": {
            "events_count":   len(events),
            "china_count":    china_count,
            "overseas_count": len(events) - china_count,
            "funding_count":  funding_count,
        },
        "events": events,
        "trends": build_trends(events),
    }

    out = Path("docs") / "data.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ 完成！{len(events)} 条事件（国内 {china_count} / 海外 {len(events)-china_count}）")
    print(f"   保存至 {out}")
    print("=" * 52)


if __name__ == "__main__":
    main()
