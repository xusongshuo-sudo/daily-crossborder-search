#!/usr/bin/env python3
"""读取 latest.md，转 HTML，用 QQ SMTP 发送"""

import html
import os
import re
import smtplib
from email.mime.text import MIMEText
from pathlib import Path


def inline_md(text: str) -> str:
    """Convert the small Markdown subset used in reports to safe inline HTML."""
    placeholders = []

    def keep_link(match: re.Match) -> str:
        label = html.escape(match.group(1), quote=False)
        url = html.escape(match.group(2), quote=True)
        placeholders.append(f'<a href="{url}">{label}</a>')
        return f"__LINK_{len(placeholders) - 1}__"

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', keep_link, text)
    text = html.escape(text, quote=False)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

    for i, value in enumerate(placeholders):
        text = text.replace(f"__LINK_{i}__", value)
    return text


def badge_class(value: str) -> str:
    if "高优先级" in value:
        return "badge badge-high"
    if "值得跟进" in value:
        return "badge badge-mid"
    return "badge"


def render_labeled_line(line: str) -> str | None:
    match = re.match(r'^\*\*([^:*：]+)[:：]\*\*\s*(.*)$', line.strip())
    if not match:
        return None

    label, value = match.group(1), match.group(2)
    if label == "推荐级别":
        return (
            '<p class="field">'
            f'<span class="field-label">{inline_md(label)}</span>'
            f'<span class="{badge_class(value)}">{inline_md(value)}</span>'
            '</p>'
        )
    return (
        '<p class="field">'
        f'<span class="field-label">{inline_md(label)}</span>'
        f'<span class="field-value">{inline_md(value)}</span>'
        '</p>'
    )


def render_summary_line(line: str) -> str:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) >= 2 and all(":" in part or "：" in part for part in parts):
        items = []
        for part in parts:
            key, value = re.split(r"[:：]", part, maxsplit=1)
            items.append(
                '<span class="metric">'
                f'<span class="metric-label">{inline_md(key.strip())}</span>'
                f'<span class="metric-value">{inline_md(value.strip())}</span>'
                '</span>'
            )
        return f'<div class="metric-row">{"".join(items)}</div>'
    return f'<p class="summary-line">{inline_md(line)}</p>'


def md2html(text: str) -> str:
    lines = text.split("\n")
    out = []
    in_card = False
    in_section = False
    in_list = False

    def close_card():
        nonlocal in_card
        if in_card:
            out.append("</div>")
            in_card = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def close_section():
        nonlocal in_section
        close_list()
        close_card()
        if in_section:
            out.append("</div>")
            in_section = False

    for line in lines:
        if line.startswith("# "):
            close_section()
            out.append(f'<div class="hero"><h1>{inline_md(line[2:])}</h1></div>')
        elif line.startswith("## "):
            close_section()
            out.append(f'<div class="section-card"><h2>{inline_md(line[3:])}</h2>')
            in_section = True
        elif line.startswith("### "):
            close_list()
            close_card()
            raw = line[4:]
            out.append(f'<div class="repo-card"><h3>{inline_md(raw)}</h3>')
            in_card = True
        elif line.startswith("> "):
            close_list()
            out.append(f'<blockquote>{inline_md(line[2:])}</blockquote>')
        elif line.startswith("---"):
            close_section()
        elif line.startswith("- "):
            if not in_list:
                out.append('<ul class="bullet-list">')
                in_list = True
            out.append(f'<li>{inline_md(line[2:])}</li>')
        elif line.strip():
            close_list()
            labeled = render_labeled_line(line)
            if labeled:
                out.append(labeled)
            elif in_card and " | " in line and any(prefix in line for prefix in ["语言:", "标签:", "创建:", "更新:", "发现层:"]):
                out.append(f'<p class="repo-meta">{inline_md(line)}</p>')
            elif in_card:
                out.append(f'<p class="card-text">{inline_md(line)}</p>')
            else:
                out.append(render_summary_line(line))
    close_section()
    return "\n".join(out)


def main():
    report_path = Path(__file__).resolve().parent.parent / "reports" / "latest.md"
    md = report_path.read_text(encoding="utf-8")
    title = md.split("\n")[0].replace("# ", "")

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
body{{
    margin: 0; padding: 0; background: #f5f7fb; color: #1f2937;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
}}
.page{{
    max-width: 680px; margin: 0 auto; padding: 20px 14px 28px;
}}
.hero{{
    background: #111827; color: #fff; border-radius: 10px;
    padding: 18px 20px; margin: 0 0 18px;
}}
h1{{ font-size: 20px; line-height: 1.35; font-weight: 700; margin: 0; }}
h2{{
    font-size: 15px; font-weight: 700; color: #111827;
    margin: 0 0 12px; padding-left: 10px; border-left: 4px solid #2563eb;
}}
.section-card{{
    background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
    padding: 14px 16px; margin: 12px 0;
}}
.summary-line{{
    margin: 8px 0; font-size: 13px; line-height: 1.65; color: #334155;
}}
.metric-row{{
    background: #f8fbff; border: 1px solid #dbeafe; border-radius: 8px;
    padding: 10px 10px 2px; margin: 8px 0;
}}
.metric{{
    display: inline-block; min-width: 128px; margin: 0 8px 8px 0;
    padding: 8px 10px; background: #eff6ff; border-radius: 7px;
}}
.metric-label{{ display: block; font-size: 11px; color: #64748b; }}
.metric-value{{ display: block; font-size: 16px; color: #0f172a; font-weight: 700; margin-top: 2px; }}
.repo-card{{
    background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
    padding: 14px 16px; margin: 10px 0 14px;
}}
h3{{ font-size: 16px; line-height: 1.45; font-weight: 700; margin: 0 0 12px; color: #111827; }}
h3 a{{ color: #2563eb; text-decoration: none; }}
a{{ color: #2563eb; text-decoration: none; }}
.field{{ margin: 7px 0; font-size: 13px; line-height: 1.55; }}
.field-label{{
    display: inline-block; width: 72px; color: #64748b; font-weight: 600;
}}
.field-value{{ color: #111827; }}
.badge{{
    display: inline-block; padding: 3px 8px; border-radius: 999px;
    background: #f1f5f9; color: #475569; font-size: 12px; font-weight: 700;
}}
.badge-high{{ background: #fee2e2; color: #b91c1c; }}
.badge-mid{{ background: #fef3c7; color: #92400e; }}
.card-text{{ font-size: 13px; color: #334155; line-height: 1.65; margin: 8px 0; }}
.bullet-list{{
    margin: 8px 0 0 18px; padding: 0; color: #334155; font-size: 13px; line-height: 1.7;
}}
.bullet-list li{{ margin: 4px 0; }}
blockquote{{
    font-size: 13px; color: #475569; margin: 10px 0; padding: 10px 12px;
    background: #f8fafc; border-left: 3px solid #cbd5e1; line-height: 1.65;
}}
.repo-meta{{
    font-size: 12px; color: #64748b; line-height: 1.6; margin: 10px 0 0;
    padding-top: 10px; border-top: 1px solid #f1f5f9;
}}
strong{{ color: #111827; font-weight: 700; }}
</style>
</head>
<body>
<div class="page">
{md2html(md)}
</div>
</body>
</html>"""

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = title
    msg["From"] = os.environ["MAIL_USERNAME"]
    msg["To"] = os.environ["MAIL_TO"]

    with smtplib.SMTP_SSL("smtp.qq.com", 465) as smtp:
        smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
        smtp.send_message(msg)

    print(f"Email sent: {title}")


if __name__ == "__main__":
    main()
