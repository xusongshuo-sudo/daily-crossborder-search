# GitHub 跨境项目分析日报

每天自动搜索 GitHub 上和跨境电商、AI Agent、Skill、运营自动化相关的项目，并生成一份中文项目分析日报。

当前逻辑不是每天列 Top 10，而是每天选择 1 个更值得看的项目做深挖分析。优先选择当天新发现的高质量项目；如果当天没有合格新增项目，就从历史候选池里选择尚未深挖过的项目补位。

## 当前日报内容

日报标题格式：

```text
GitHub 跨境项目分析日报 - YYYY-MM-DD
```

每份日报主要包含：

- 今日结论：候选项目数量、今日新增数量、累计追踪数量、已深挖数量
- 今日深挖项目：项目链接、推荐级别、质量评分、项目定位、主分类
- 选择原因：为什么今天选这个项目
- 基本信息：stars、forks、language、topics、创建时间、更新时间、发现层级
- 内容摘选：从 README 中提取具体高质量内容，并用中文说明能对应到哪些跨境运营场景
- README 观察：判断 README 是否有 Agent、Skill、Prompt、MCP、安装、示例、API 等落地信号
- 成熟度判断
- 风险和不足
- 建议动作

最新报告示例：

- `reports/latest.md`
- `reports/2026-06-29.md`

## 搜索策略

搜索仍保持较宽的关键词范围，避免因为关键词太窄漏掉有价值的新项目。质量判断放在后置筛选和日报分析阶段完成。

三层搜索漏斗：

```text
Layer 1: 近 2 日新创建
Layer 2: 3-14 日前创建
Layer 3: 长期热门项目
```

当前关键词组：

| 关键词组 | 示例关键词 |
| --- | --- |
| 跨境电商+AI Skill | `cross-border ecommerce AI`, `跨境电商 Claude Code skill`, `Amazon AI agent tool`, `跨境电商 agent` |
| 选品/运营 AI | `ecommerce product research AI agent`, `Amazon listing AI optimization`, `ecommerce keyword research AI`, `跨境电商 选品 AI` |
| 电商+Agent/MCP | `ecommerce AI agent automation`, `ecommerce MCP skill tool`, `跨境电商 AI 工具`, `Amazon seller AI assistant` |

基础相关性过滤要求项目同时命中：

- 电商/跨境相关词：如 `ecommerce`, `amazon`, `listing`, `shopify`, `supplier`, `跨境`, `选品`, `供应链`
- AI/Agent 相关词：如 `ai`, `agent`, `llm`, `skill`, `mcp`, `prompt`, `claude`, `codex`

## 选中逻辑

每天选择一个项目，顺序如下：

1. 今日新增项目优先。
2. 今日没有合格新增时，从历史未深挖项目补位。
3. 如果仍然没有合格项目，再使用低门槛补位。

项目质量评分是 0-100 分，重点看：

- 是否有明确跨境业务场景
- 是否有 AI Agent / Skill / Prompt / MCP 等自动化信号
- README 和描述是否完整
- topics 是否完整
- 最近是否有更新
- 是否有主要代码语言和可运行信号
- stars 只作为辅助，不作为唯一标准

偏导航、合集、教程、纯 demo、低星展示页的项目会被降权或排除。

## 已深挖项目怎么看

主要看 `seen.json`。

如果某个项目有下面字段，就表示已经被深挖过：

```json
{
  "full_name": "nexscope-ai/eCommerce-Skills",
  "stars": 295,
  "first_seen": "2026-06-29T02:56:44.021769+00:00",
  "analyzed_at": "2026-06-29T08:30:11.535576+00:00",
  "analysis_score": 94,
  "analysis_source": "历史未分析补位"
}
```

字段含义：

- `first_seen`：第一次被系统发现的时间
- `analyzed_at`：被选为日报深挖项目的时间
- `analysis_score`：当时的质量评分
- `analysis_source`：来自今日新增、历史未分析补位或低门槛补位

如果想取消某个项目的“已深挖”标识，删除该项目下的这 3 个字段即可：

```json
"analyzed_at": "...",
"analysis_score": 94,
"analysis_source": "历史未分析补位"
```

## 候选项目怎么看

每次运行会生成候选池文件：

- `reports/candidates-latest.json`
- `reports/candidates-YYYY-MM-DD.json`

候选池里每个项目会包含：

- `quality_score`
- `strengths`
- `concerns`
- `platform_hits`
- `agent_hits`
- `is_new_today`
- `already_analyzed`
- `is_deep_dive_candidate`

如果想看还有哪些项目没有深挖，可以在 `reports/candidates-latest.json` 里筛选：

```json
"already_analyzed": false
```

## GitHub Actions 自动运行

工作流文件：

```text
.github/workflows/daily-search.yml
```

触发方式：

- 每天 UTC 0:00 自动运行一次，也就是北京时间 8:00
- 支持在 GitHub Actions 页面手动点击 `Run workflow`

工作流会执行：

1. 运行 `scripts/search.py`
2. 更新 `seen.json` 和 `reports/`
3. 自动提交日报结果
4. 运行 `scripts/send_email.py` 发送邮件

## GitHub Secrets 配置

到仓库的 `Settings -> Secrets and variables -> Actions` 添加：

| Secret | 用途 |
| --- | --- |
| `GH_TOKEN` | GitHub API Token，用于提高搜索接口额度 |
| `MAIL_USERNAME` | 发件邮箱账号 |
| `MAIL_PASSWORD` | 发件邮箱 SMTP 授权码 |
| `MAIL_TO` | 收件邮箱 |

当前邮件脚本使用 QQ 邮箱 SMTP：

```text
smtp.qq.com:465
```

如果要添加多个收件邮箱，可以在 `MAIL_TO` 中使用英文逗号分隔，例如：

```text
a@example.com,b@example.com
```

## 本地运行

Windows PowerShell 示例：

```powershell
$env:GH_TOKEN="你的 GitHub Token"
python scripts\search.py
```

发送邮件：

```powershell
$env:MAIL_USERNAME="你的发件邮箱"
$env:MAIL_PASSWORD="你的 SMTP 授权码"
$env:MAIL_TO="收件邮箱"
python scripts\send_email.py
```

如果只想看本地日报结果，运行 `scripts/search.py` 后查看：

```text
reports/latest.md
```

## 文件说明

```text
.
├── .github/workflows/daily-search.yml   # GitHub Actions 定时任务
├── scripts/search.py                    # 搜索、筛选、评分、日报生成
├── scripts/send_email.py                # 邮件 HTML 渲染与发送
├── seen.json                            # 已发现项目和已深挖状态
├── reports/
│   ├── latest.md                        # 最新日报
│   ├── YYYY-MM-DD.md                    # 每日归档日报
│   ├── candidates-latest.json           # 最新候选池
│   └── candidates-YYYY-MM-DD.json       # 每日候选池归档
└── README.md
```

## 注意事项

- `analyzed.json` 是本地辅助文件，不需要提交；线上持久化以 `seen.json` 为准。
- 不要把 GitHub Token、邮箱授权码等密钥写进代码或 README。
- 如果手动修改 `seen.json`，注意保持 JSON 格式合法，尤其是最后一项不要多余逗号。
