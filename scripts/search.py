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


def is_garbage(repo: dict) -> bool:
    """检测垃圾项目：minified代码、无意义描述等"""
    desc = (repo.get("description") or "").strip()
    name = repo.get("name", "").lower()

    # 描述太短
    if len(desc) < 15:
        return True
    # minified JS / 压缩代码
    if any(p in desc for p in ["(function(", "var n;function", "/*  Copyright", "SPDX-License"]):
        return True
    # 纯数字/符号占大多数
    alpha = sum(1 for c in desc if c.isalpha() or c.isspace())
    if len(desc) > 0 and alpha / len(desc) < 0.4:
        return True
    # 名称特征可疑
    if any(w in name for w in ["dictatorship", "china-dictat", "propaganda"]):
        return True
    return False


def repo_score(repo: dict) -> float:
    """综合评分：星标 + 时效 + 内容质量"""
    from datetime import timedelta

    stars = repo.get("stargazers_count") or repo.get("stars", 0) or 0
    desc = (repo.get("description") or "").strip()
    pushed = repo.get("pushed_at", "")
    topics = repo.get("topics", []) or []

    s = 0
    # 星标分（对数压缩，避免高星完全碾压新项目）
    s += min(stars, 500) * 0.6
    s += max(0, stars - 500) * 0.1  # 超过 500 星标权重降低

    # 时效分：最近半年内有更新 + 最高 200
    if pushed:
        try:
            dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
            if age_days < 180:
                s += max(0, 200 - age_days)  # 越新越加分
        except:
            pass

    # 描述质量分
    if 50 <= len(desc) <= 500:
        s += 50
    elif len(desc) > 500:
        s += 30

    # 标签分
    if len(topics) >= 3:
        s += 40
    elif len(topics) >= 1:
        s += 20

    return s


def is_relevant(repo: dict) -> bool:
    """判断项目是否同时涉及电商和AI，且不是垃圾"""
    if is_garbage(repo):
        return False

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


REPORT_TZ = timezone(timedelta(hours=8))


def report_date() -> str:
    return datetime.now(REPORT_TZ).strftime("%Y-%m-%d")


def short_desc(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def active_label(repo: dict) -> str:
    pushed = repo.get("pushed_at", "")
    if not pushed:
        return "无更新时间"
    try:
        dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
    except ValueError:
        return "更新时间未知"

    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days <= 7:
        return "7日内活跃"
    if age_days <= 30:
        return "30日内活跃"
    if age_days <= 180:
        return "半年内活跃"
    return "长期未更新"


def recommendation_level(repo: dict) -> str:
    score = repo_score(repo)
    stars = repo.get("stars", 0)
    if score >= 260 or stars >= 100:
        return "高优先级"
    if score >= 120 or stars >= 20:
        return "值得跟进"
    return "观察"


def action_hint(repo: dict) -> str:
    category = repo.get("category", "")
    if category == "选品/市场调研":
        return "优先看数据源、评分逻辑和是否能迁移到现有选品流程。"
    if category == "Listing/文案优化":
        return "优先看输入字段、输出结构和是否支持 Amazon listing 场景。"
    if category == "Skill/提示词模板":
        return "优先看技能目录结构、提示词质量和是否能直接复用到 Codex/Claude Code。"
    if category == "图片/视觉设计":
        return "优先看示例图、提示词模板和批量生成能力。"
    if category == "广告投放":
        return "优先看投放指标、账户接入方式和是否只停留在 demo。"
    if category == "供应链/采购":
        return "优先看供应商数据来源、1688/Alibaba 接入和风控字段。"
    if category == "订单/库存管理":
        return "优先看平台接口、状态同步和自托管成本。"
    return "先快速浏览 README、示例和最近提交，判断是否值得深入试用。"


def why_watch(repo: dict) -> str:
    reasons = []
    stars = repo.get("stars", 0)
    if stars >= 100:
        reasons.append(f"{stars} stars，已有较强关注度")
    elif stars >= 20:
        reasons.append(f"{stars} stars，有一定早期关注")
    else:
        reasons.append(f"{stars} stars，偏早期项目")

    label = active_label(repo)
    if label != "无更新时间":
        reasons.append(label)
    if repo.get("language"):
        reasons.append(f"主要语言 {repo['language']}")
    if repo.get("keyword_group"):
        reasons.append(f"来自「{repo['keyword_group']}」搜索组")

    return "；".join(reasons) + "。"


def category_counts(items: list[dict]) -> list[tuple[str, int]]:
    counts = {}
    for item in items:
        category = item.get("category", "未分类")
        counts[category] = counts.get(category, 0) + 1
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))


def generate_overview(top_items: list[dict], all_results: list[dict], seen: dict) -> list[str]:
    lines = [
        "## 今日速览",
        "",
        f"新增项目: {len(all_results)} | 累计追踪: {len(seen)} | 报告口径: 新增优先，按星标、活跃度、描述质量和标签完整度综合排序",
        "",
    ]

    if not top_items:
        lines.extend([
            "今天没有新的候选项目，下面展示历史高星项目，适合作为长期参考清单。",
            "",
        ])
        return lines

    high_count = sum(1 for item in top_items if recommendation_level(item) == "高优先级")
    categories = "，".join(f"{name} {count}" for name, count in category_counts(top_items)[:5])
    top_repo = max(top_items, key=lambda x: x.get("stars", 0))
    newest_repo = max(top_items, key=lambda x: x.get("created_at", ""))

    lines.extend([
        f"高优先级: {high_count} 个 | 覆盖分类: {categories}",
        "",
        f"最高星项目: [{top_repo['full_name']}]({top_repo['html_url']}) ({top_repo['stars']} stars)",
        "",
        f"最新创建项目: [{newest_repo['full_name']}]({newest_repo['html_url']}) (创建于 {newest_repo['created_at'][:10]})",
        "",
    ])
    return lines


def render_priority_pick(repo: dict, index: int) -> list[str]:
    return [
        f"### {index}. [{repo['full_name']}]({repo['html_url']}) | {recommendation_level(repo)}",
        "",
        f"{repo.get('category', '未分类')}。{why_watch(repo)}{action_hint(repo)}",
        "",
    ]


def render_repo(repo: dict, index: int | None = None) -> list[str]:
    prefix = f"{index}. " if index is not None else ""
    desc = short_desc(repo.get("description", ""))
    topics = ", ".join(repo.get("topics", [])[:5]) if repo.get("topics") else ""

    lines = [
        f"### {prefix}[{repo['full_name']}]({repo['html_url']}) | {repo.get('stars', 0)} stars",
        "",
        f"**推荐级别:** {recommendation_level(repo)}",
        "",
        f"**定位:** {repo.get('cn_summary', '未识别')}",
        "",
        f"**分类:** {repo.get('category', '未分类')}",
        "",
        f"**为什么看:** {why_watch(repo)}",
        "",
        f"**建议动作:** {action_hint(repo)}",
        "",
    ]

    if desc:
        lines.extend([f"> {desc}", ""])

    meta = []
    if repo.get("language"):
        meta.append(f"语言: {repo['language']}")
    if topics:
        meta.append(f"标签: {topics}")
    if repo.get("created_at"):
        meta.append(f"创建: {repo['created_at'][:10]}")
    if repo.get("pushed_at"):
        meta.append(f"更新: {repo['pushed_at'][:10]}")
    if repo.get("layer"):
        meta.append(f"发现层: {repo['layer']}")
    lines.extend([" | ".join(meta), "", "---", ""])
    return lines


def generate_report(all_results: list[dict], seen: dict) -> str:
    today = report_date()
    lines = [
        f"# GitHub 跨境电商+AI 日报 - {today}",
        "",
    ]

    # 取 Top 10（新增优先，无新增时取历史高星）
    if all_results:
        top10 = sorted(all_results, key=repo_score, reverse=True)[:10]
        label = "## 今日精选 Top 10"
    else:
        label = "## 今日无新增 · 历史 Top 10"
        top10 = []
        for rid, info in seen.items():
            top10.append({
                "full_name": info.get("full_name", ""),
                "html_url": f"https://github.com/{info.get('full_name', '')}",
                "stars": info.get("stars", 0),
                "cn_summary": "已追踪项目",
                "category": "历史记录",
                "description": "",
                "language": "",
                "topics": [],
                "created_at": info.get("first_seen", "")[:10],
                "pushed_at": "",
            })
        top10 = sorted(top10, key=lambda x: x["stars"], reverse=True)[:10]

    lines.extend(generate_overview(top10, all_results, seen))

    if all_results and top10:
        lines.extend(["## 优先看这 3 个", ""])
        for i, r in enumerate(top10[:3], 1):
            lines.extend(render_priority_pick(r, i))

    lines.append(label)
    lines.append("")

    for i, r in enumerate(top10, 1):
        lines.extend(render_repo(r, i))

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

    report = generate_report(fresh, seen)
    today_str = report_date()
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
