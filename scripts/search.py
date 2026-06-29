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
ANALYZED_FILE = REPO_ROOT / "analyzed.json"
REPORT_DIR = REPO_ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)

GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")
BASE_URL = "https://api.github.com/search/repositories"
REPO_API_URL = "https://api.github.com/repos"
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


def text_blob(repo: dict) -> str:
    return " ".join([
        repo.get("full_name", ""),
        repo.get("name", ""),
        repo.get("description") or "",
        " ".join(repo.get("topics", [])),
        repo.get("language") or "",
    ]).lower()


def quality_profile(repo: dict) -> dict:
    """Score repository quality while keeping search keywords broad."""
    text = text_blob(repo)
    score = 0
    strengths = []
    concerns = []

    stars = repo.get("stars", repo.get("stargazers_count", 0)) or 0
    topics = repo.get("topics", []) or []
    desc = (repo.get("description") or "").strip()
    language = repo.get("language") or ""

    if stars >= 100:
        score += 16
        strengths.append("已有较高关注度")
    elif stars >= 20:
        score += 10
        strengths.append("已有一定早期关注")
    elif stars >= 5:
        score += 5
        strengths.append("有少量早期关注")
    else:
        concerns.append("关注度较低")

    if is_recently_active(repo, 30):
        score += 16
        strengths.append("最近 30 天有更新")
    elif is_recently_active(repo, 90):
        score += 10
        strengths.append("最近 90 天有更新")
    elif is_recently_active(repo, 180):
        score += 5
        strengths.append("半年内有更新")
    else:
        concerns.append("近期维护信号弱")

    if desc and len(desc) >= 40:
        score += 10
        strengths.append("描述信息较完整")
    elif desc:
        score += 4
        concerns.append("描述偏短")
    else:
        concerns.append("缺少项目描述")

    if len(topics) >= 4:
        score += 8
        strengths.append("topics 较完整")
    elif topics:
        score += 4

    platform_terms = [
        "amazon", "shopify", "tiktok shop", "tiktok", "shopee", "etsy", "ebay",
        "1688", "alibaba", "aliexpress", "ozon", "listing", "product research",
        "supplier", "keyword", "ppc", "cross-border", "cross border", "跨境",
        "选品", "供应链", "关键词", "竞品",
    ]
    platform_hits = [term for term in platform_terms if term in text]
    if len(platform_hits) >= 2:
        score += 18
        strengths.append("跨境业务场景明确")
    elif platform_hits:
        score += 9
        strengths.append("有跨境业务关键词")
    else:
        concerns.append("跨境业务场景不够明确")

    agent_terms = [
        "agent", "skill", "mcp", "claude", "codex", "openclaw", "cursor",
        "automation", "llm", "prompt", "ai-agent", "ai agent",
    ]
    agent_hits = [term for term in agent_terms if term in text]
    if len(agent_hits) >= 2:
        score += 16
        strengths.append("AI Agent/Skill 信号明确")
    elif agent_hits:
        score += 8
        strengths.append("有 AI 工具信号")
    else:
        concerns.append("AI 工具属性不够明确")

    runnable_terms = [
        "python", "typescript", "javascript", "go", "java", "docker", "fastapi",
        "nextjs", "react", "cli", "sdk", "api", "server", "app",
    ]
    if language and language.lower() not in ["html", "css"]:
        score += 10
        strengths.append(f"有主要代码语言：{language}")
    elif any(term in text for term in runnable_terms):
        score += 6
        strengths.append("有可运行工具信号")
    else:
        concerns.append("可运行代码信号不足")

    negative_terms = [
        "awesome", "curated list", "collection of", "directory", "navigation",
        "tutorial", "course", "sample", "demo only", "template only",
        "导航", "收录", "资源合集", "工具合集", "课程", "教程", "示例项目",
    ]
    negative_hits = [term for term in negative_terms if term in text]
    if negative_hits:
        score -= 30
        concerns.append("偏合集/教程/导航，落地价值需谨慎")

    if language.lower() == "html" and stars < 20:
        score -= 10
        concerns.append("低星 HTML 项目可能偏展示页")

    score = max(0, min(100, score))
    return {
        "quality_score": score,
        "strengths": strengths[:5],
        "concerns": concerns[:5],
        "platform_hits": platform_hits[:6],
        "agent_hits": agent_hits[:6],
        "is_deep_dive_candidate": score >= 58 and not negative_hits,
    }


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


def load_analyzed() -> dict:
    if ANALYZED_FILE.exists():
        with open(ANALYZED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def merge_analyzed_from_seen(analyzed: dict, seen: dict) -> dict:
    merged = dict(analyzed)
    for rid, info in seen.items():
        if info.get("analyzed_at"):
            merged.setdefault(rid, {
                "full_name": info.get("full_name", ""),
                "html_url": info.get("html_url", ""),
                "analyzed_at": info.get("analyzed_at", ""),
                "score": info.get("analysis_score", 0),
                "source": info.get("analysis_source", "seen.json"),
            })
    return merged


def save_seen(data: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_analyzed(data: dict):
    with open(ANALYZED_FILE, "w", encoding="utf-8") as f:
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


def fetch_readme(full_name: str, retry: int = 2) -> str:
    url = f"{REPO_API_URL}/{quote(full_name, safe='/')}/readme"
    headers = dict(HEADERS)
    headers["Accept"] = "application/vnd.github.raw"

    for attempt in range(retry):
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=30) as resp:
                wait_for_rate_limit(dict(resp.headers))
                return resp.read().decode("utf-8", errors="replace")[:12000]
        except HTTPError as e:
            if e.code == 404:
                return ""
            if e.code == 403 and attempt < retry - 1:
                time.sleep(15)
        except Exception:
            if attempt < retry - 1:
                time.sleep(5)
    return ""


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
                "category": item["category"],
                "description": item["description"],
                "html_url": item["html_url"],
                "language": item["language"],
                "topics": item["topics"],
                "created_at": item["created_at"],
                "pushed_at": item["pushed_at"],
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
    return fresh


def unique_by_repo(items: list[dict]) -> list[dict]:
    unique = {}
    for item in items:
        rid = str(item["id"])
        if rid not in unique or repo_score(item) > repo_score(unique[rid]):
            unique[rid] = item
    return list(unique.values())


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
    score = quality_profile(repo)["quality_score"]
    if score >= 76:
        return "高优先级"
    if score >= 58:
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


def is_recently_active(repo: dict, max_days: int = 180) -> bool:
    pushed = repo.get("pushed_at", "")
    if not pushed:
        return False
    try:
        dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - dt).days <= max_days


def is_quality_candidate(repo: dict) -> bool:
    profile = quality_profile(repo)
    return bool(profile["is_deep_dive_candidate"])


def is_directory_like_repo(repo: dict) -> bool:
    text = " ".join([
        repo.get("full_name", ""),
        repo.get("description", ""),
        " ".join(repo.get("topics", [])),
    ]).lower()
    directory_terms = [
        "awesome", "curated list", "collection of", "directory", "navigation",
        "导航", "收录", "资源合集", "工具合集", "站点仓库", "网址",
    ]
    return any(term in text for term in directory_terms)


def select_daily_project(fresh: list[dict], all_candidates: list[dict], analyzed: dict) -> tuple[dict | None, str]:
    analyzed_ids = set(analyzed.keys())
    fresh_pool = [
        item for item in unique_by_repo(fresh)
        if str(item["id"]) not in analyzed_ids and is_quality_candidate(item)
    ]
    if fresh_pool:
        return sorted(fresh_pool, key=lambda x: (quality_profile(x)["quality_score"], repo_score(x)), reverse=True)[0], "今日新增"

    history_pool = [
        item for item in unique_by_repo(all_candidates)
        if str(item["id"]) not in analyzed_ids and is_quality_candidate(item)
    ]
    if history_pool:
        return sorted(history_pool, key=lambda x: (quality_profile(x)["quality_score"], repo_score(x)), reverse=True)[0], "历史未分析补位"

    fallback_pool = [
        item for item in unique_by_repo(all_candidates)
        if str(item["id"]) not in analyzed_ids and item.get("stars", 0) > 0
    ]
    if fallback_pool:
        return sorted(fallback_pool, key=lambda x: (quality_profile(x)["quality_score"], repo_score(x)), reverse=True)[0], "低门槛补位"

    return None, "无候选"


def candidate_record(repo: dict, analyzed: dict, fresh_ids: set[str]) -> dict:
    profile = quality_profile(repo)
    rid = str(repo["id"])
    return {
        "id": rid,
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "description": repo.get("description", ""),
        "stars": repo.get("stars", 0),
        "forks": repo.get("forks", 0),
        "language": repo.get("language", ""),
        "topics": repo.get("topics", []),
        "category": repo.get("category", ""),
        "cn_summary": repo.get("cn_summary", ""),
        "keyword_group": repo.get("keyword_group", ""),
        "layer": repo.get("layer", ""),
        "repo_score": round(repo_score(repo), 2),
        "quality_score": profile["quality_score"],
        "strengths": profile["strengths"],
        "concerns": profile["concerns"],
        "platform_hits": profile["platform_hits"],
        "agent_hits": profile["agent_hits"],
        "is_new_today": rid in fresh_ids,
        "already_analyzed": rid in analyzed,
        "is_deep_dive_candidate": profile["is_deep_dive_candidate"],
        "created_at": repo.get("created_at", ""),
        "pushed_at": repo.get("pushed_at", ""),
    }


def save_candidates_report(candidates: list[dict], fresh: list[dict], analyzed: dict):
    fresh_ids = {str(item["id"]) for item in fresh}
    records = [candidate_record(item, analyzed, fresh_ids) for item in unique_by_repo(candidates)]
    records.sort(key=lambda x: (x["is_deep_dive_candidate"], x["quality_score"], x["repo_score"]), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(records),
        "fresh_count": len(fresh_ids),
        "deep_dive_candidate_count": sum(1 for item in records if item["is_deep_dive_candidate"]),
        "items": records,
    }
    today = report_date()
    paths = [
        REPORT_DIR / f"candidates-{today}.json",
        REPORT_DIR / "candidates-latest.json",
    ]
    for path in paths:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


def readme_flags(readme: str) -> dict[str, bool]:
    text = readme.lower()
    return {
        "has_install": any(w in text for w in ["install", "installation", "pip install", "npm install", "安装"]),
        "has_usage": any(w in text for w in ["usage", "quick start", "example", "demo", "使用", "示例"]),
        "has_api": any(w in text for w in ["api", "token", "credential", "oauth", "apikey", "接口"]),
        "has_license": "license" in text or "mit" in text or "apache" in text,
        "has_skill": any(w in text for w in ["skill", "prompt", "agent", "mcp", "claude", "codex"]),
    }


def maturity_judgement(repo: dict, readme: str) -> str:
    flags = readme_flags(readme)
    points = 0
    points += 1 if repo.get("stars", 0) >= 20 else 0
    points += 1 if is_recently_active(repo, 30) else 0
    points += 1 if repo.get("topics") else 0
    points += 1 if flags["has_install"] else 0
    points += 1 if flags["has_usage"] else 0

    if points >= 4:
        return "成熟度较高：项目关注度、活跃度和 README 信息都比较完整，值得优先打开验证。"
    if points >= 2:
        return "成熟度中等：有明确方向，但仍需要检查 README、示例和实际代码完整度。"
    return "成熟度偏早期：适合先收藏观察，不建议直接投入生产流程。"


def quality_summary(repo: dict, readme: str) -> str:
    profile = quality_profile(repo)
    strengths = "、".join(profile["strengths"]) if profile["strengths"] else "暂无明显加分项"
    concerns = "、".join(profile["concerns"]) if profile["concerns"] else "暂无明显扣分项"
    readme_note = "README 已读取，可辅助判断实际能力。" if readme else "README 未读取到，主要依赖仓库元信息判断。"
    return (
        f"质量分 {profile['quality_score']}/100。主要加分项：{strengths}。"
        f"主要疑点：{concerns}。{readme_note}"
    )


def problem_statement(repo: dict, readme: str) -> str:
    category = repo.get("category", "")
    features = repo.get("cn_summary", "")
    if "图片/视觉设计" in features:
        return "它主要面向商品主图、详情页图、社媒推广图等跨境视觉素材，适合提升电商图片生产和转化导向设计效率。"
    if "Listing优化/文案" in features:
        return "它主要面向商品标题、五点描述、关键词或 A+ 内容，适合辅助提升 Listing 产出效率。"
    if "选品调研" in features or "竞品/市场分析" in features or category == "选品/市场调研":
        return "它主要面向选品、竞品或市场判断，适合用来缩短跨境卖家在产品机会筛选上的信息整理时间。"
    if "供应链/采购" in features or category == "供应链/采购":
        return "它主要面向供应商、采购或 1688/Alibaba 场景，适合做上游货源筛选和询盘辅助。"
    if "订单/库存管理" in features or category == "订单/库存管理":
        return "它主要面向刊登、订单、库存或运营工作流，适合评估是否能接入现有店铺后台。"
    if readme_flags(readme)["has_skill"]:
        return "它更像 AI Agent / Skill / Prompt 资产，适合拆解为可复用的跨境运营能力模块。"
    return "它覆盖跨境电商与 AI 工具交叉场景，适合先判断是否能服务具体运营环节。"


def landing_scenarios(repo: dict) -> list[str]:
    category = repo.get("category", "")
    features = repo.get("cn_summary", "")
    if "图片/视觉设计" in features:
        return ["主图/详情页图提示词复用", "社媒推广图批量生成", "视觉素材生产流程标准化"]
    if "Listing优化/文案" in features:
        return ["Amazon 标题和五点描述初稿", "关键词覆盖检查", "批量 Listing 改写和本地化"]
    if "选品调研" in features or "竞品/市场分析" in features or category == "选品/市场调研":
        return ["新品调研前的候选池筛选", "竞品卖点和市场信息整理", "把人工调研步骤沉淀为 Agent 工作流"]
    if "供应链/采购" in features or category == "供应链/采购":
        return ["供应商初筛", "采购询盘前的信息整理", "1688/Alibaba 货源判断"]
    if "订单/库存管理" in features or category == "订单/库存管理":
        return ["订单状态和库存数据整合", "运营后台自动化", "自托管工具链评估"]
    return ["拆解 README 和示例", "收藏为跨境 AI 工具池", "参考其 Agent / Skill 结构"]


def risk_notes(repo: dict, readme: str) -> list[str]:
    risks = []
    flags = readme_flags(readme)
    if not readme:
        risks.append("未读取到 README，无法确认安装方式和真实能力边界。")
    if not flags["has_install"]:
        risks.append("README 中安装说明不明显，落地前需要确认能否快速跑起来。")
    if not flags["has_usage"]:
        risks.append("示例或使用说明不明显，需要防止只是概念仓库。")
    if not is_recently_active(repo, 30):
        risks.append("最近 30 天活跃度一般，建议检查 issue 和 commit 维护情况。")
    if repo.get("stars", 0) < 10:
        risks.append("关注度仍低，适合小范围验证，不宜直接依赖。")
    return risks or ["暂无明显结构性风险，主要风险在于实际接入成本和数据源可用性。"]


def clean_readme_line(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
    line = re.sub(r"<[^>]+>", "", line)
    return re.sub(r"\s+", " ", line.strip(" #*-`\t|")).strip()


def readme_candidate_lines(readme: str) -> list[str]:
    if not readme:
        return []

    lines = []
    for raw in readme.splitlines():
        lower = raw.lower()
        if not raw.strip():
            continue
        if raw.lstrip().startswith("![") or "shields.io" in lower or "badge" in lower:
            continue
        if raw.lstrip().startswith(("http://", "https://", "```")):
            continue
        if set(raw.strip()) <= {"-", "|", ":", " "}:
            continue

        if raw.count("|") >= 2:
            cells = [clean_readme_line(cell) for cell in raw.split("|")]
            line = " / ".join(cell for cell in cells if cell)
        else:
            line = clean_readme_line(raw)

        if 18 <= len(line) <= 220:
            lines.append(line)
    return lines


def content_signals(text: str) -> list[str]:
    lower = text.lower()
    mapping = [
        ("product research", "产品调研/选品判断"),
        ("market research", "市场调研"),
        ("competitor", "竞品分析"),
        ("keyword", "关键词研究"),
        ("listing", "Listing 优化/审核"),
        ("seo", "SEO 优化"),
        ("review", "评论/评价分析"),
        ("pricing", "定价分析"),
        ("ppc", "广告投放/PPC"),
        ("ads", "广告投放"),
        ("marketing automation", "营销自动化"),
        ("supply chain", "供应链优化"),
        ("supplier", "供应商筛选"),
        ("inventory", "库存运营"),
        ("analytics", "业务数据分析"),
        ("business analytics", "业务数据分析"),
        ("image", "商品图片/视觉素材"),
        ("agent", "AI Agent 自动化"),
        ("skill", "可复用 Skill 模块"),
        ("prompt", "提示词资产"),
        ("api", "API/数据接入"),
        ("amazon", "Amazon"),
        ("shopify", "Shopify"),
        ("tiktok shop", "TikTok Shop"),
        ("etsy", "Etsy"),
        ("ebay", "eBay"),
        ("walmart", "Walmart"),
    ]
    signals = []
    for term, label in mapping:
        if term in lower and label not in signals:
            signals.append(label)
    return signals


def content_example_sentence(signals: list[str]) -> str:
    parts = []
    if "产品调研/选品判断" in signals or "市场调研" in signals:
        parts.append("用于新品机会筛选和市场判断")
    if "竞品分析" in signals:
        parts.append("用于拆解竞品卖点、价格和市场位置")
    if "关键词研究" in signals or "SEO 优化" in signals:
        parts.append("用于检查关键词覆盖和搜索流量机会")
    if "Listing 优化/审核" in signals:
        parts.append("用于优化商品标题、五点描述或页面信息")
    if "广告投放/PPC" in signals:
        parts.append("用于辅助广告词、投放结构或 PPC 分析")
    if "供应链优化" in signals or "供应商筛选" in signals:
        parts.append("用于供应商筛选、采购判断或供应链流程优化")
    if "业务数据分析" in signals:
        parts.append("用于把销售、运营或市场数据整理成决策依据")
    if "定价分析" in signals:
        parts.append("用于价格带、利润空间或竞品定价判断")
    if "AI Agent 自动化" in signals or "可复用 Skill 模块" in signals or "提示词资产" in signals:
        parts.append("适合沉淀成可复用的 AI 运营 Skill")

    if not parts:
        return "可作为判断项目是否值得打开验证的具体内容依据。"
    return "；".join(parts[:3]) + "。"


def readme_content_examples(readme: str) -> list[str]:
    if not readme:
        return ["未读取到 README，暂时无法摘选具体内容。"]

    scored = []
    for line in readme_candidate_lines(readme):
        signals = content_signals(line)
        if not signals:
            continue
        score = len(signals)
        if any(item in signals for item in ["产品调研/选品判断", "竞品分析", "关键词研究", "Listing 优化/审核", "供应链优化", "业务数据分析"]):
            score += 3
        if any(item in signals for item in ["Amazon", "Shopify", "TikTok Shop", "Etsy", "eBay", "Walmart"]):
            score += 2
        if any(item in signals for item in ["AI Agent 自动化", "可复用 Skill 模块", "提示词资产"]):
            score += 1
        scored.append((score, signals, line))

    scored.sort(key=lambda item: item[0], reverse=True)
    examples = []
    seen = set()
    for _, signals, line in scored:
        key = "、".join(signals[:4])
        if key in seen:
            continue
        seen.add(key)
        examples.append(f"包含「{key}」：{content_example_sentence(signals)}")
        if len(examples) >= 4:
            break

    if examples:
        return examples
    return ["README 已读取，但没有自动识别出足够具体的业务内容，建议人工查看目录结构和示例文件。"]


def readme_observation(repo: dict, readme: str) -> list[str]:
    if not readme:
        return ["未读取到 README，暂时只能依赖仓库描述、topics、语言和更新时间判断。"]

    flags = readme_flags(readme)
    profile = quality_profile(repo)
    notes = []

    if flags["has_skill"]:
        notes.append("README 明确出现 Agent、Skill、Prompt、MCP、Claude 或 Codex 等信号，项目更像可复用的 AI 运营能力模块。")
    if profile["platform_hits"]:
        platforms = "、".join(profile["platform_hits"][:4])
        notes.append(f"README 或仓库元信息覆盖 {platforms} 等跨境业务关键词，场景不是泛 AI 工具。")
    if flags["has_usage"]:
        notes.append("README 中有示例、使用方式或 quick start 信号，后续验证成本相对低。")
    if flags["has_install"]:
        notes.append("README 中能看到安装或部署信号，适合进一步检查是否能本地跑通。")
    if flags["has_api"]:
        notes.append("README 提到 API、token 或 credential，落地时需要重点确认数据源和账号权限。")

    if not flags["has_usage"]:
        notes.append("使用示例信号不明显，需要打开仓库目录确认是否只是说明性资产。")
    if not flags["has_install"]:
        notes.append("安装说明不够明显，建议先确认是否能直接接入现有工作流。")

    return notes[:5] if notes else ["README 已读取，但可落地信息不够集中，建议人工打开目录和示例进一步确认。"]


def generate_report(selected: dict | None, source: str, fresh_count: int, candidate_count: int, seen: dict, analyzed: dict, readme: str) -> str:
    today = report_date()
    lines = [
        f"# GitHub 跨境项目分析日报 - {today}",
        "",
        "## 今日结论",
        "",
        f"候选项目: {candidate_count} | 今日新增: {fresh_count} | 累计追踪: {len(seen)} | 已深挖: {len(analyzed)}",
        "",
    ]

    if not selected:
        lines.extend([
            "今天没有找到未分析过的合格跨境项目。建议明天继续搜索，或降低最低质量门槛。",
            "",
        ])
        return "\n".join(lines)

    topics = ", ".join(selected.get("topics", [])[:6]) if selected.get("topics") else "无"
    risks = risk_notes(selected, readme)
    profile = quality_profile(selected)

    lines.extend([
        f"今天选择 **{source}** 项目：[{selected['full_name']}]({selected['html_url']})。",
        "",
        f"一句话判断：{problem_statement(selected, readme)}",
        "",
        f"## 今日深挖项目：[{selected['full_name']}]({selected['html_url']})",
        "",
        f"**推荐级别:** {recommendation_level(selected)}",
        "",
        f"**质量评分:** {profile['quality_score']}/100",
        "",
        f"**项目定位:** {selected.get('cn_summary', '未识别')}",
        "",
        f"**主分类:** {selected.get('category', '未分类')}",
        "",
        f"**选择原因:** {quality_summary(selected, readme)}来源为「{source}」，且尚未做过深度分析。",
        "",
        "## 基本信息",
        "",
        f"stars: {selected.get('stars', 0)} | forks: {selected.get('forks', 0)} | language: {selected.get('language') or '未知'} | topics: {topics}",
        "",
        f"created: {selected.get('created_at', '')[:10]} | pushed: {selected.get('pushed_at', '')[:10]} | found: {selected.get('layer', '未知层级')}",
        "",
        "## 内容摘选",
        "",
    ])
    for item in readme_content_examples(readme):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## README 观察",
        "",
    ])
    for item in readme_observation(selected, readme):
        lines.append(f"- {item}")

    lines.extend([
        "",
        "## 成熟度判断",
        "",
        maturity_judgement(selected, readme),
        "",
        "## 风险和不足",
        "",
    ])
    for item in risks:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "## 建议动作",
        "",
        action_hint(selected),
        "",
        "建议今天只做一件事：打开 README 和示例目录，判断它是否能被拆成你自己的跨境运营 Agent / Skill 模块。",
        "",
    ])

    return "\n".join(lines)


def main():
    print("=" * 50)
    print(f"GitHub 跨境项目分析日报 - {datetime.now(timezone.utc).isoformat()}")
    print(f"Token: {'已设置' if GITHUB_TOKEN else '未设置'}")
    print("=" * 50)

    seen = load_seen()
    analyzed = merge_analyzed_from_seen(load_analyzed(), seen)
    print(f"已追踪: {len(seen)} 个")
    print(f"已深挖: {len(analyzed)} 个")

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

    all_raw = unique_by_repo(layer3 + layer2 + layer1)
    print(f"\n去重前: {len(all_raw)}")
    fresh = deduplicate(all_raw, seen)
    print(f"新增: {len(fresh)}")
    save_candidates_report(all_raw, fresh, analyzed)

    selected, source = select_daily_project(fresh, all_raw, analyzed)
    readme = ""
    if selected:
        print(f"今日深挖: {selected['full_name']} ({source})")
        readme = fetch_readme(selected["full_name"])
        analyzed_at = datetime.now(timezone.utc).isoformat()
        score = quality_profile(selected)["quality_score"]
        analyzed[str(selected["id"])] = {
            "full_name": selected["full_name"],
            "html_url": selected["html_url"],
            "analyzed_at": analyzed_at,
            "score": score,
            "source": source,
        }
        seen.setdefault(str(selected["id"]), {
            "full_name": selected["full_name"],
            "stars": selected["stars"],
            "first_seen": datetime.now(timezone.utc).isoformat(),
        })
        seen[str(selected["id"])].update({
            "analyzed_at": analyzed_at,
            "analysis_score": score,
            "analysis_source": source,
        })
    else:
        print("今日无合格深挖项目")

    save_seen(seen)
    save_analyzed(analyzed)

    report = generate_report(selected, source, len(fresh), len(all_raw), seen, analyzed, readme)
    today_str = report_date()
    report_path = REPORT_DIR / f"{today_str}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    latest_path = REPORT_DIR / "latest.md"
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告: {report_path}")

    print("\n" + "=" * 50)
    if selected:
        print(f"{source}: {selected['stars']}s {selected['full_name']}")
        print(f"分类: {selected['category']}")
        print(f"README: {'已读取' if readme else '未读取到'}")


if __name__ == "__main__":
    main()
