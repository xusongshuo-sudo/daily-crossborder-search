#!/usr/bin/env python3
"""
GitHub 跨境电商+AI 项目每日搜索
三层漏斗策略：近2日新创 → 3-14日前 → 长期热门（去重）
"""

import os
import json
import time
import sys
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

# GitHub Token（GitHub Actions 自动注入，本地跑可不设）
GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")
BASE_URL = "https://api.github.com/search/repositories"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "github-daily-search",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# ── 搜索策略 ──────────────────────────────────────────────
# 三层：近2天 / 3-14天 / 不限时间
# 每层多个关键词组，覆盖跨境电商、AI Agent、选品运营

KEYWORD_GROUPS = {
    "跨境电商+AI": [
        "cross-border ecommerce AI skill",
        "跨境电商 AI agent",
        "Amazon AI tool ecommerce",
        "AliExpress AI automation",
    ],
    "Claude Code Agent": [
        "Claude Code skill",
        "agent skill template",
        "MCP skill agent",
        "cursor rule AI agent",
    ],
    "选品运营AI": [
        "product research AI agent ecommerce",
        "listing optimization AI",
        "keyword research AI ecommerce",
        "ecommerce competitor analysis AI",
    ],
}

PER_PAGE = 15  # 每组最多取 15 条


# ── 工具函数 ──────────────────────────────────────────────
def load_seen() -> dict:
    """加载已见过的项目 ID 集合"""
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(data: dict):
    """保存已见项目"""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def api_call(query: str, page: int = 1) -> dict:
    """调用 GitHub Search API，带重试和限速处理"""
    url = f"{BASE_URL}?q={quote(query)}&sort=stars&order=desc&per_page={PER_PAGE}&page={page}"
    time.sleep(2.5)  # 无 token 时 10次/分钟 → 间隔 6 秒，有 token 30次/分钟 → 间隔 2 秒

    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"  ! API error {e.code}: {body[:300]}")
        return {"items": []}


def extract_fields(repo: dict, keyword_group: str, layer: str) -> dict:
    """提取需要的字段"""
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "description": repo["description"] or "",
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


# ── 主逻辑 ────────────────────────────────────────────────
def search_layer(days_back: int | None, days_back_end: int | None, layer_name: str) -> list[dict]:
    """
    执行一层搜索。
    如果 days_back=None，不限时间。
    如果 days_back_end=None，搜 days_back 天内。
    否则搜 days_back ~ days_back_end 天前。
    """
    # 构造时间范围
    if days_back is None:
        date_range = ""  # 不限
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
            print(f"  [{group_name}] 搜索: {query}")
            data = api_call(query)
            repos = data.get("items", [])
            print(f"    → 找到 {len(repos)} 个")
            for repo in repos:
                results.append(extract_fields(repo, group_name, layer_name))
            time.sleep(1)  # 请求间隔

    return results


def deduplicate(items: list[dict], seen: dict) -> list[dict]:
    """去重：按 repo id，同时排除 seen.json 中已有的，并排除 stars=0 的"""
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
    """生成 Markdown 日报"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# GitHub 跨境电商+AI 日报 — {today}",
        "",
        f"**累计已追踪项目数：{seen_count}**  ",
        f"**本次新增：{len(all_results)} 个**",
        "",
        "---",
        "",
    ]

    if not all_results:
        lines.append("今日无新增项目。")
        return "\n".join(lines)

    # 按层级分组
    for layer in ["Layer 1: 近2日新创", "Layer 2: 3-14日前", "Layer 3: 长期热门"]:
        layer_items = [r for r in all_results if r["layer"] == layer]
        if not layer_items:
            continue

        # 去重（同层内可能重复）
        seen_urls = set()
        unique_items = []
        for r in layer_items:
            if r["html_url"] not in seen_urls:
                seen_urls.add(r["html_url"])
                unique_items.append(r)

        lines.append(f"## {layer}（{len(unique_items)} 个）")
        lines.append("")

        for r in sorted(unique_items, key=lambda x: x["stars"], reverse=True):
            desc = (r["description"] or "无描述").replace("\n", " ")[:200]
            topics = ", ".join(r["topics"][:5]) if r["topics"] else ""
            lines.append(f"### ⭐ {r['stars']} [{r['full_name']}]({r['html_url']})")
            lines.append(f"")
            lines.append(f"> {desc}")
            lines.append(f"")
            meta_parts = [f"🔖 关键词组: {r['keyword_group']}"]
            if r["language"]:
                meta_parts.append(f"💻 {r['language']}")
            if topics:
                meta_parts.append(f"🏷️ {topics}")
            meta_parts.append(f"创建: {r['created_at'][:10]}")
            meta_parts.append(f"最近更新: {r['pushed_at'][:10]}")
            lines.append(" | ".join(meta_parts))
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 50)
    print(f"GitHub 跨境电商+AI 每日搜索 — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 50)

    # 加载已见项目
    seen = load_seen()
    print(f"已追踪项目: {len(seen)} 个")

    # ── 第1层: 近2天 ──
    print("\n[Layer 1] 搜索近2天新创建的项目...")
    layer1 = search_layer(days_back=2, days_back_end=None, layer_name="Layer 1: 近2日新创")
    print(f"  Layer 1 原始结果: {len(layer1)}")

    # ── 第2层: 3-14天 ──
    print("\n[Layer 2] 搜索3-14天前创建的项目...")
    layer2 = search_layer(days_back=14, days_back_end=3, layer_name="Layer 2: 3-14日前")
    print(f"  Layer 2 原始结果: {len(layer2)}")

    # ── 第3层: 不限时间 ──
    print("\n[Layer 3] 搜索不限时间的长期热门项目...")
    layer3 = search_layer(days_back=None, days_back_end=None, layer_name="Layer 3: 长期热门")
    print(f"  Layer 3 原始结果: {len(layer3)}")

    # 合并 + 去重（按3→2→1优先级，但都以 seen 为准）
    all_raw = layer3 + layer2 + layer1
    print(f"\n去重前总数: {len(all_raw)}")
    fresh = deduplicate(all_raw, seen)
    print(f"去重后新增: {len(fresh)}")

    # 保存 seen
    save_seen(seen)

    # 生成报告
    report = generate_report(fresh, len(seen))
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = REPORT_DIR / f"{today_str}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已生成: {report_path}")

    # 同时写一个 latest.md（方便快速查看）
    latest_path = REPORT_DIR / "latest.md"
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"最新报告: {latest_path}")

    # 打印摘要
    print("\n" + "=" * 50)
    print("摘要")
    print("=" * 50)
    for layer in ["Layer 1: 近2日新创", "Layer 2: 3-14日前", "Layer 3: 长期热门"]:
        count = len([r for r in fresh if r["layer"] == layer])
        top3 = sorted(
            [r for r in fresh if r["layer"] == layer],
            key=lambda x: x["stars"], reverse=True
        )[:3]
        print(f"\n{layer}: {count} 个新增")
        for r in top3:
            print(f"  ⭐{r['stars']} {r['full_name']} — {r['description'][:80]}")


if __name__ == "__main__":
    main()
