#!/usr/bin/env python3
"""读取 latest.md，转 HTML，用 QQ SMTP 发送"""

import os, re, smtplib
from email.mime.text import MIMEText
from pathlib import Path


def md2html(text: str) -> str:
    lines = text.split("\n")
    out = []
    for line in lines:
        if line.startswith("# "):
            out.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith("## "):
            out.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith("### "):
            raw = line[4:]
            raw = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', raw)
            out.append(f'<h3>{raw}</h3>')
        elif line.startswith("> "):
            out.append(f'<blockquote>{line[2:]}</blockquote>')
        elif line.startswith("---"):
            out.append('<hr>')
        elif line.strip().startswith("**") and line.strip().endswith("**"):
            inner = line.strip()[2:-2]
            inner = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', inner)
            out.append(f'<p><strong>{inner}</strong></p>')
        elif line.strip():
            line2 = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', line)
            line2 = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line2)
            line2 = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line2)
            out.append(f'<p>{line2}</p>')
        else:
            out.append('<br>')
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
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 640px; margin: 0 auto; padding: 16px;
    background: #fff; color: #222;
}}
h1{{ font-size: 18px; font-weight: 600; margin: 0 0 16px; padding-bottom: 8px; border-bottom: 1px solid #eee; }}
h2{{ font-size: 13px; font-weight: 600; color: #999; margin: 24px 0 12px; letter-spacing: 0.5px; }}
h3{{ font-size: 15px; font-weight: 600; margin: 16px 0 2px; }}
h3 a{{ color: #0366d6; text-decoration: none; }}
a{{ color: #0366d6; }}
blockquote{{
    font-size: 13px; color: #666; margin: 2px 0 8px; padding: 0;
    border: none; line-height: 1.5;
}}
hr{{ border: 0; border-top: 1px solid #f0f0f0; margin: 14px 0; }}
p{{ margin: 1px 0; font-size: 12px; color: #999; }}
strong{{ color: #333; font-weight: 500; }}
</style>
</head>
<body>
{md2html(md)}
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
