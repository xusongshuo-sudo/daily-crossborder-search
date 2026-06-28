# GitHub 跨境电商+AI 每日搜索

每天自动搜索 GitHub 上与跨境电商、AI Agent、Claude Code Skill 相关的高质量新项目。

## 搜索策略（三层漏斗）

```
第1层：近2日新创建 → 按星标排序，抢最新
  ↓ 去重
第2层：3-14日前创建 → 补漏近两周的
  ↓ 去重
第3层：不限时间长期热门 → 发现之前没扫到的高星项目
```

每层用多个关键词组并行搜索：

| 关键词组 | 覆盖范围 |
|----------|----------|
| 跨境电商+AI | cross-border ecommerce, Amazon, AliExpress |
| Claude Code Agent | Claude Code skill, agent template, MCP, cursor rule |
| 选品运营AI | product research, listing optimization, keyword, competitor |

## 部署步骤

### 1. 创建 GitHub 仓库

在 GitHub 网页上新建一个**私有仓库**（建议），名字随便，比如 `daily-crossborder-search`。

> ⚠️ 不要勾选 "Add a README file"，用下面的代码覆盖即可。

### 2. 推送代码

```bash
cd C:\workspace\28-github-daily-search

git init
git add .
git commit -m "init: daily crossborder AI search"
git branch -M main
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

### 3. 配置 Token（重要 ⚠️）

脚本需要 GitHub Token 才能调用搜索 API（免 Token 限速太厉害）。

1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token (classic)
3. 勾选 `public_repo` 权限
4. 复制生成的 token（类似 `ghp_xxxxxxxxxxxx`）

然后到仓库的 **Settings → Secrets and variables → Actions**：

1. 点 **New repository secret**
2. Name: `GH_TOKEN`
3. Value: 粘贴刚才的 token
4. 点 **Add secret**

### 4. 手动测试一次

到仓库的 **Actions** 标签页 → 点左侧 **Daily GitHub Search** → 点 **Run workflow** → **Run workflow**

等几分钟，跑完后在 `reports/` 目录下就能看到当天报告。

### 5. 确认定时触发

Workflow 会每天 UTC 0:00（北京时间 8:00）自动跑一次。之后每天到仓库的 `reports/` 目录看最新报告即可。

## 查看结果

- `reports/2026-06-29.md` — 每日详细报告
- `reports/latest.md` — 最新报告（方便直接打开）
- `seen.json` — 去重记录，自动维护

## 本地测试（可选）

```bash
# 设置 token 环境变量
export GH_TOKEN=ghp_你的token

# 跑一次
python scripts/search.py
```

## 文件说明

```
.
├── .github/workflows/daily-search.yml  # GitHub Actions 定时任务
├── scripts/search.py                   # 搜索脚本
├── seen.json                          # 去重记录（自动维护）
├── reports/                           # 日报输出（自动生成）
└── README.md
```
