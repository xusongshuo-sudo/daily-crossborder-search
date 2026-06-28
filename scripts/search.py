#!/usr/bin/env python3
"""
GitHub 跨境电商+AI 项目每日搜索
三层漏斗策略：近2日新创 → 3-14日前 → 长期热门（去重）
每个项目附带中文简介 + 相关性过滤
"""

import os
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError

# ── 配置 ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
SEEN_FILE = REPO_ROOT / "seen.json"
REPORT_DIR = REPO_ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)

GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")
BASE_URL = "https://api.github.com/search/repositories"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "daily-crossborder-search",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# ── 搜索关键词 ─────────────────────────────────────────────
KEYWORD_GROUPS = {
    "跨境电商+AI Skill": [
        "cross-border ecommerce AI",
        "跨境电商 Claude Code skill",
        "Amazon AI agent tool",
        "跨境电商 agent",
    ],
    "选品/运营 AI": [
        "ecommerce product research AI agent",
        "Amazon listing AI optimization",
        "ecommerce keyword research AI",
        "跨境电商 选品 AI",
    ],
    "电商+Agent/MCP": [
        "ecommerce AI agent automation",
        "ecommerce MCP skill tool",
        "跨境电商 AI 工具",
        "Amazon seller AI assistant",
    ],
}

PER_PAGE = 15


# ── 相关性过滤 ─────────────────────────────────────────────
# 项目的描述/标签必须同时命中至少一个"电商词"和一个"AI词"

ECOMMERCE_TERMS = [
    "ecommerce", "e-commerce", "shop", "store", "product",
    "listing", "amazon", "aliexpress", "seller", "retail",
    "电商", "跨境", "选品", "运营", "店铺", "marketplace",
    "shopify", "ebay", "ozon", "商品", "supplier", "供应链",
]

AI_TERMS = [
    "ai", "agent", "claude", "llm", "gpt", "skill", "mcp",
    "automation", "prompt", "machine learning", "人工智能",
    "deepseek", "cursor", "codex", "openclaw", "大模型",
]

# 黑名单：含这些词的项目直接排除
BLACKLIST = [
    "dictatorship", "propaganda", "censorship", "arrest",
    "genocide", "uighur", "tibet", "falun", "tiananmen",
    "gambling", "porn", "casino",
]


def is_relevant(repo: dict) -> bool:
    """判断项目是否同时涉及电商和AI"""
    text = " ".join([
        repo.get("description") or "",
        repo.get("name", ""),
        " ".join(repo.get("topics", [])),
    ]).lower()

    # 黑名单检查
    for bad in BLACKLIST:
        if bad in text:
            return False

    has_ecom = any(term in text for term in ECOMMERCE_TERMS)
    has_ai = any(term in text for term in AI_TERMS)
    return has_ecom and has_ai


# ── 功能分类 ─────────────────────────────────────────────
# 每个项目归类到一个主分类

FUNCTION_CATEGORIES = {
    "Skill/提示词模板": ["AI技能/提示词模板"],
    "AI Agent/自动化": ["AI Agent自动化"],
    "选品/市场调研": ["选品调研", "竞品/市场分析"],
    "Listing/文案优化": ["Listing优化/文案"],
    "关键词/SEO": ["关键词/SEO"],
    "图片/视觉设计": ["图片/视觉设计"],
    "广告投放": ["广告投放"],
    "供应链/采购": ["供应链/采购"],
    "社媒/内容营销": ["社媒/内容营销"],
    "定价/利润分析": ["定价/利润分析"],
    "订单/库存管理": ["订单/库存管理"],
    "翻译/本地化": ["翻译/本地化"],
    "客服/售后": ["客服/售后"],
}

def classify_repo(repo_data: dict) -> str:
    """根据功能标签确定主分类"""
    summary = repo_data.get("cn_summary", "")
    # cn_summary 现在是逗号分隔的功能标签
    features = [f.strip() for f in summary.split("，")]

    # 按优先级匹配：更具体的分类优先
    priority = [
        "Skill/提示词模板", "选品/市场调研", "Listing/文案优化",
        "图片/视觉设计", "关键词/SEO", "广告投放",
        "AI Agent/自动化", "社媒/内容营销",
        "供应链/采购", "定价/利润分析", "订单/库存管理",
        "翻译/本地化", "客服/售后",
    ]

    for cat in priority:
        cat_features = FUNCTION_CATEGORIES.get(cat, [])
        for feat in features:
            if feat in cat_features:
                return cat

    # 检查原始描述中的补充信号
    desc = (repo_data.get("description", "")).lower()
    name = repo_data.get("full_name", "").lower()
    text = f"{name} {desc}"

    if any(w in text for w in ["skill", "prompt", "提示词"]):
        return "Skill/提示词模板"
    if any(w in text for w in ["agent", "自动化"]):
        return "AI Agent/自动化"
    if any(w in text for w in ["选品", "research", "市场"]):
        return "选品/市场调研"
    if any(w in text for w in ["listing", "文案"]):
        return "Listing/文案优化"
    if any(w in text for w in ["image", "图片", "视觉"]):
        return "图片/视觉设计"

    return "综合电商AI工具"


# ── 中文简介生成 ───────────────────────────────────────────
def make_cn_summary(repo: dict, keyword_group: str) -> str:
    """为项目生成一句话中文简介：返回功能标签列表"""
    desc = (repo.get("description") or "").lower()
    name = repo.get("name", "").lower()
    text = f"{name} {desc}"

    # 识别具体功能
    features = []
    if any(w in text for w in ["选品", "product research", "product selection"]):
        features.append("选品调研")
    if any(w in text for w in ["listing", "文案", "copywriting", "copywriter"]):
        features.append("Listing优化/文案")
    if any(w in text for w in ["keyword", "关键词", "seo"]):
        features.append("关键词/SEO")
    if any(w in text for w in ["竞品", "competitor", "market research", "市场"]):
        features.append("竞品/市场分析")
    if any(w in text for w in ["图片", "image", "a+", "aplus", "视觉"]):
        features.append("图片/视觉设计")
    if any(w in text for w in ["广告", "advertising", "ppc", "ad "]):
        features.append("广告投放")
    if any(w in text for w in ["supplier", "供应链", "采购", "1688"]):
        features.append("供应链/采购")
    if any(w in text for w in ["客服", "customer service", "售后"]):
        features.append("客服/售后")
    if any(w in text for w in ["automation", "自动化", "agent"]):
        features.append("AI Agent自动化")
    if any(w in text for w in ["mcp", "skill", "prompt"]):
        features.append("AI技能/提示词模板")
    if any(w in text for w in ["translat", "翻译"]):
        features.append("翻译/本地化")
    if any(w in text for w in ["price", "定价", "profit", "利润"]):
        features.append("定价/利润分析")
    if any(w in text for w in ["inventory", "库存", "order"]):
        features.append("订单/库存管理")
    if any(w in text for w in ["tiktok", "social", "社媒", "youtube"]):
        features.append("社媒/内容营销")

    if not features:
        features.append("跨境电商AI工具")

    return "，".join(features[:4])


# ── API 工具函数 ──────────────────────────────────────────
def load_seen() -> dict:
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(data: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def wait_for_rate_limit(headers: dict):
    remaining = int(headers.get("X-RateLimit-Remaining", 30))
    if remaining < 3:
        reset_time = int(headers.get("X-RateLimit-Reset", time.time() + 10))
        wait = max(reset_time - time.time(), 1) + 1
        print(f"    速率限制接近，等待 {wait:.0f}s...")
        time.sleep(wait)


def api_call(query: str, retry: int = 3) -> dict:
    url = f"{BASE_URL}?q={quote(query)}&sort=stars&order=desc&per_page={PER_PAGE}"

    for attempt in range(retry):
        req = Request(url, headers=HEADERS)
        try:
            with urlopen(req, timeout=30) as resp:
                wait_for_rate_limit(dict(resp.headers))
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 403:
                print(f"    限速，等待 15s ({attempt+1}/{retry})...")
                time.sleep(15)
                continue
            elif e.code == 422:
                return {"items": []}
            else:
                return {"items": []}
        except Exception:
            if attempt < retry - 1:
                time.sleep(5)
            else:
                return {"items": []}
    return {"items": []}


def extract_fields(repo: dict, keyword_group: str, layer: str) -> dict:
    cn_summary = make_cn_summary(repo, keyword_group)
    category = classify_repo({"cn_summary": cn_summary, "description": repo.get("description", ""), "full_name": repo.get("full_name", "")})
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "description": repo["description"] or "",
        "cn_summary": cn_summary,
        "category": category,
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "language": repo["language"] or "",
        "topics": repo.get("topics", []),
        "created_at": repo["created_at"],
        "updated_at": repo["updated_at"],
        "pushed_at": repo["pushed_at"],
        "keyword_group": keyword_group,
        "layer": layer,
        "found_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 搜索逻辑 ──────────────────────────────────────────────
def search_layer(days_back: int | None, days_back_end: int | None, layer_name: str) -> list[dict]:
    if days_back is None:
        date_range = ""
    elif days_back_end is None:
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        date_range = f"created:>={since}"
    else:
        start = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end = (datetime.now(timezone.utc) - timedelta(days=days_back_end)).strftime("%Y-%m-%d")
        date_range = f"created:{start}..{end}"

    results = []
    for group_name, keywords in KEYWORD_GROUPS.items():
        for kw in keywords:
            query = f"{kw}+{date_range}" if date_range else kw
            print(f"  [{group_name}] {query}")
            data = api_call(query)
            repos = data.get("items", [])
            # 相关性过滤
            relevant = [r for r in repos if is_relevant(r)]
            print(f"    -> {len(repos)} 个（过滤后 {len(relevant)}）")
            for repo in relevant:
                results.append(extract_fields(repo, group_name, layer_name))
            time.sleep(4)
    return results


def deduplicate(items: list[dict], seen: dict) -> list[dict]:
    fresh = []
    for item in items:
        rid = str(item["id"])
        if rid not in seen and item["stars"] > 0:
            fresh.append(item)
            seen[rid] = {
                "full_name": item["full_name"],
                "stars": item["stars"],
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
    return fresh


def generate_report(all_results: list[dict], seen_count: int) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# GitHub 跨境电商+AI 日报 - {today}",
        "",
        f"**累计追踪项目：{seen_count}** | **本次新增：{len(all_results)} 个**",
        "",
        "---",
        "",
    ]

    if not all_results:
        lines.append("今日无新增相关项目。")
        return "\n".join(lines)

    # 按功能分类分组
    from collections import Counter, defaultdict
    category_items = defaultdict(list)
    for r in all_results:
        category_items[r["category"]].append(r)

    # 排序：热门分类优先
    sorted_cats = sorted(category_items.keys(),
        key=lambda c: (len(category_items[c]), max(x["stars"] for x in category_items[c])),
        reverse=True)

    # 取 Top 10（按星标排序）
    top10 = sorted(all_results, key=lambda x: x["stars"], reverse=True)[:10]

    lines.append("## 今日精选 Top 10")
    lines.append("")

    for i, r in enumerate(top10, 1):
        desc = (r["description"] or "").replace("\n", " ")[:200]
        topics = ", ".join(r["topics"][:5]) if r["topics"] else ""

        lines.append(f"### {i}. [{r['full_name']}]({r['html_url']})  ⭐ {r['stars']}")
        lines.append("")
        lines.append(f"**📌 {r['cn_summary']}**")
        lines.append(f"**🏷️ {r['category']}**")
        lines.append("")
        if desc:
            lines.append(f"> {desc}")
            lines.append("")

        meta = []
        if r["language"]:
            meta.append(f"语言: {r['language']}")
        if topics:
            meta.append(f"标签: {topics}")
        meta.append(f"创建: {r['created_at'][:10]}")
        lines.append(" | ".join(meta))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 50)
    print(f"GitHub 跨境电商+AI 每日搜索 - {datetime.now(timezone.utc).isoformat()}")
    print(f"Token: {'已设置' if GITHUB_TOKEN else '未设置'}")
    print("=" * 50)

    seen = load_seen()
    print(f"已追踪: {len(seen)} 个")

    for label, days, days_end in [
        ("Layer 1: 近2日新创", 2, None),
        ("Layer 2: 3-14日前", 14, 3),
        ("Layer 3: 长期热门", None, None),
    ]:
        print(f"\n[{label}]")
        layer_results = search_layer(days, days_end, label)
        print(f"  {label}: {len(layer_results)} 个")
        if days is None:
            layer3 = layer_results
        elif days == 2:
            layer1 = layer_results
        else:
            layer2 = layer_results

    all_raw = layer3 + layer2 + layer1
    print(f"\n去重前: {len(all_raw)}")
    fresh = deduplicate(all_raw, seen)
    print(f"新增: {len(fresh)}")

    save_seen(seen)

    report = generate_report(fresh, len(seen))
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = REPORT_DIR / f"{today_str}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    latest_path = REPORT_DIR / "latest.md"
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告: {report_path}")

    print("\n" + "=" * 50)
    for layer in ["Layer 1: 近2日新创", "Layer 2: 3-14日前", "Layer 3: 长期热门"]:
        items = [r for r in fresh if r["layer"] == layer]
        top3 = sorted(items, key=lambda x: x["stars"], reverse=True)[:3]
        print(f"\n{layer}: {len(items)} 个新增")
        for r in top3:
            print(f"  {r['stars']}s {r['full_name']}")
            print(f"    {r['cn_summary']}")


if __name__ == "__main__":
    main()
