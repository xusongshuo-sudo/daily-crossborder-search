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
    return (
        repo.get("stars", 0) >= 5
        and bool(repo.get("description"))
        and is_recently_active(repo)
        and repo_score(repo) >= 120
        and not is_directory_like_repo(repo)
    )


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
        return sorted(fresh_pool, key=repo_score, reverse=True)[0], "今日新增"

    history_pool = [
        item for item in unique_by_repo(all_candidates)
        if str(item["id"]) not in analyzed_ids and is_quality_candidate(item)
    ]
    if history_pool:
        return sorted(history_pool, key=repo_score, reverse=True)[0], "历史未分析补位"

    fallback_pool = [
        item for item in unique_by_repo(all_candidates)
        if str(item["id"]) not in analyzed_ids and item.get("stars", 0) > 0
    ]
    if fallback_pool:
        return sorted(fallback_pool, key=repo_score, reverse=True)[0], "低门槛补位"

    return None, "无候选"


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


def readme_excerpt(readme: str) -> str:
    if not readme:
        return "未读取到 README 内容。"
    lines = []
    for line in readme.splitlines():
        line = line.strip(" #\t")
        lower = line.lower()
        if not line:
            continue
        if line.startswith("![") or "<img" in lower:
            continue
        if "shields.io" in lower or "badge" in lower:
            continue
        if re.fullmatch(r"\[?[^\]]+\]?\([^)]+\)", line):
            continue
        if line.startswith(("http://", "https://", "```", "|", "<p", "</p", "<div", "</div")):
            continue
        if 20 <= len(line) <= 180 and not line.startswith(("http://", "https://", "```", "|")):
            lines.append(line)
        if len(lines) >= 2:
            break
    return " / ".join(lines) if lines else short_desc(readme, 240)


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
    scenarios = landing_scenarios(selected)
    risks = risk_notes(selected, readme)

    lines.extend([
        f"今天选择 **{source}** 项目：[{selected['full_name']}]({selected['html_url']})。",
        "",
        f"一句话判断：{problem_statement(selected, readme)}",
        "",
        f"## 今日深挖项目：[{selected['full_name']}]({selected['html_url']})",
        "",
        f"**推荐级别:** {recommendation_level(selected)}",
        "",
        f"**综合评分:** {repo_score(selected):.1f}",
        "",
        f"**项目定位:** {selected.get('cn_summary', '未识别')}",
        "",
        f"**主分类:** {selected.get('category', '未分类')}",
        "",
        f"**选择原因:** {why_watch(selected)}来源为「{source}」，且尚未做过深度分析。",
        "",
        "## 基本信息",
        "",
        f"stars: {selected.get('stars', 0)} | forks: {selected.get('forks', 0)} | language: {selected.get('language') or '未知'} | topics: {topics}",
        "",
        f"created: {selected.get('created_at', '')[:10]} | pushed: {selected.get('pushed_at', '')[:10]} | found: {selected.get('layer', '未知层级')}",
        "",
        "## 它解决什么跨境问题",
        "",
        problem_statement(selected, readme),
        "",
        "## README 观察",
        "",
        readme_excerpt(readme),
        "",
        "## 可落地场景",
        "",
    ])
    for item in scenarios:
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

    selected, source = select_daily_project(fresh, all_raw, analyzed)
    readme = ""
    if selected:
        print(f"今日深挖: {selected['full_name']} ({source})")
        readme = fetch_readme(selected["full_name"])
        analyzed_at = datetime.now(timezone.utc).isoformat()
        score = round(repo_score(selected), 2)
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
