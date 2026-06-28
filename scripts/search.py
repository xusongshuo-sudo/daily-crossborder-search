#!/usr/bin/env python3
"""
GitHub 跨境电商+AI 项目每日搜索
三层漏斗策略：近2日新创 → 3-14日前 → 长期热门（去重）
"""

import os
import json
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

# ── 搜索策略 ──────────────────────────────────────────────
# 每层 9 个关键词（3组 × 3个），共 27 次 API 调用
# 间隔 4s，约 11 次/分钟，远低于 30 次/分钟的限额

KEYWORD_GROUPS = {
    "跨境电商+AI": [
        "cross-border ecommerce AI skill",
        "跨境电商 AI agent",
        "Amazon AI tool ecommerce",
    ],
    "Claude Code Agent": [
        "Claude Code skill",
        "agent skill template",
        "MCP AI agent",
    ],
    "选品运营AI": [
        "product research AI ecommerce",
        "listing optimization AI",
        "ecommerce competitor AI agent",
    ],
}

PER_PAGE = 15


# ── 工具函数 ──────────────────────────────────────────────
def load_seen() -> dict:
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(data: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def wait_for_rate_limit(headers: dict):
    """检查速率限制，如果剩余次数 < 3，等待到重置"""
    remaining = int(headers.get("X-RateLimit-Remaining", 30))
    if remaining < 3:
        reset_time = int(headers.get("X-RateLimit-Reset", time.time() + 10))
        wait = max(reset_time - time.time(), 1) + 1
        print(f"    速率限制接近，等待 {wait:.0f}s...")
        time.sleep(wait)


def api_call(query: str, retry: int = 3) -> dict:
    """调用 GitHub Search API，自动处理速率限制和重试"""
    url = f"{BASE_URL}?q={quote(query)}&sort=stars&order=desc&per_page={PER_PAGE}"

    for attempt in range(retry):
        req = Request(url, headers=HEADERS)
        try:
            with urlopen(req, timeout=30) as resp:
                wait_for_rate_limit(dict(resp.headers))
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 403:
                # 速率限制，等待后重试
                print(f"    速率限制，等待 15s 后重试 ({attempt+1}/{retry})...")
                time.sleep(15)
                continue
            elif e.code == 422:
                # 查询语法错误（通常是时间范围有问题），跳过
                body = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
                print(f"    查询错误 422: {body}")
                return {"items": []}
            else:
                body = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
                print(f"    API 错误 {e.code}: {body}")
                return {"items": []}
        except Exception as ex:
            print(f"    网络错误: {ex}")
            if attempt < retry - 1:
                time.sleep(5)
            else:
                return {"items": []}

    return {"items": []}


def extract_fields(repo: dict, keyword_group: str, layer: str) -> dict:
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
    """执行一层搜索"""
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
            print(f"    -> {len(repos)} 个")
            for repo in repos:
                results.append(extract_fields(repo, group_name, layer_name))
            time.sleep(4)  # 每次调用间隔 4 秒，确保低于速率限制

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
        f"**累计已追踪项目数：{seen_count}**  ",
        f"**本次新增：{len(all_results)} 个**",
        "",
        "---",
        "",
    ]

    if not all_results:
        lines.append("今日无新增项目。")
        return "\n".join(lines)

    for layer in ["Layer 1: 近2日新创", "Layer 2: 3-14日前", "Layer 3: 长期热门"]:
        layer_items = [r for r in all_results if r["layer"] == layer]
        if not layer_items:
            continue

        seen_urls = set()
        unique_items = []
        for r in layer_items:
            if r["html_url"] not in seen_urls:
                seen_urls.add(r["html_url"])
                unique_items.append(r)

        lines.append(f"## {layer}（{len(unique_items)} 个）")
        lines.append("")

        for r in sorted(unique_items, key=lambda x: x["stars"], reverse=True):
            desc = (r["description"] or "").replace("\n", " ")[:200]
            topics = ", ".join(r["topics"][:5]) if r["topics"] else ""
            lines.append(f"### [{r['full_name']}]({r['html_url']}) - Stars: {r['stars']}")
            lines.append("")
            if desc:
                lines.append(f"> {desc}")
                lines.append("")
            meta = [f"关键词: {r['keyword_group']}"]
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
    print(f"Token: {'已设置' if GITHUB_TOKEN else '未设置（限速更严）'}")
    print("=" * 50)

    seen = load_seen()
    print(f"已追踪项目: {len(seen)} 个")

    print("\n[Layer 1] 近2天新创建...")
    layer1 = search_layer(2, None, "Layer 1: 近2日新创")
    print(f"  Layer 1: {len(layer1)} 个")

    print("\n[Layer 2] 3-14天前...")
    layer2 = search_layer(14, 3, "Layer 2: 3-14日前")
    print(f"  Layer 2: {len(layer2)} 个")

    print("\n[Layer 3] 不限时间...")
    layer3 = search_layer(None, None, "Layer 3: 长期热门")
    print(f"  Layer 3: {len(layer3)} 个")

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
    print(f"报告: {report_path}")

    latest_path = REPORT_DIR / "latest.md"
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report)

    print("\n" + "=" * 50)
    for layer in ["Layer 1: 近2日新创", "Layer 2: 3-14日前", "Layer 3: 长期热门"]:
        count = len([r for r in fresh if r["layer"] == layer])
        top3 = sorted([r for r in fresh if r["layer"] == layer], key=lambda x: x["stars"], reverse=True)[:3]
        print(f"{layer}: {count} 个新增")
        for r in top3:
            desc = (r["description"] or "")[:80]
            print(f"  {r['stars']}s {r['full_name']} - {desc}")


if __name__ == "__main__":
    main()
