# 求职 Agent 交接文档

## 给接手程序员的 30 秒摘要

这是一个全自动求职 Agent，运行在 Linux 服务器上，提供 Web UI（端口 5000）。
用户填入 AI 网关地址和 API Key，提供信息源（腾讯文档/Boss 直聘/猎聘），
Agent 自动采集岗位 -> AI 评分 -> 自动填表投递 -> 人工审核 -> 进度看板。

## 当前状态

### 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| 配置系统 | ✅ | YAML 配置，Web UI 可编辑保存 |
| 采集器（腾讯文档） | ✅ | 通过 MCP 接口采集 SmartSheet 岗位，已跑通 1258 条 |
| 采集器（Boss/猎聘） | ⚠️ | 代码已写，未测试（需要用户填 token） |
| AI 评分 | ✅ | GLM 网关评分，支持维度明细（匹配/前景/地点/稳定性/薪资） |
| Web UI | ✅ | Flask 单文件，4 个 Tab（看板/列表/审核/配置） |
| 后台运行 | ✅ | 线程化运行，切 Tab 不中断，实时日志轮询 |
| Playwright 浏览器自动化 | ✅ | 已安装 Chromium，headless 模式 |
| 智能投递（smart_apply） | ✅ | AI 搜索官网 -> 验证URL -> Playwright打开 -> 找入口 -> 填表 |
| 截图反馈 | ✅ | 每步操作截图 base64 编码返回前端显示 |

### 未完成 / 已知问题

| 问题 | 优先级 | 说明 |
|------|--------|------|
| 网申系统需要登录 | P0 | Moka/zhiye 等系统点"申请职位"后弹出登录框，需要手机号+验证码。当前无法自动登录。需要加"通用手机号输入 -> 等待用户输入验证码 -> 登录后填表"的流程 |
| 评分太慢 | P1 | 893 个岗位串行调 AI，每个约 3-5 秒，总计 45-75 分钟。需要改批量评分（一次发 10 个岗位给 AI） |
| 789 个岗位是微信公众号链接 | P1 | 这些链接不是标准网申系统，Playwright 打开后没有表单。需要 AI 搜索官网流程处理（已实现但成功率不高） |
| 116 个岗位有标准网申链接 | - | 这些是 Moka/zhiye/feishu/hotjob 系统，Playwright 能打开并检测表单 |
| 分数维度明细只对新评的岗位有效 | P2 | 旧评分数据没有 dimensions 字段，需要重新评分 |
| 前端无错误提示 | P2 | AI 填表超时（约 60-120 秒）时前端只显示转圈，无进度 |

## 架构

```
career-ops/
├── agent/                    # Agent 主代码
│   ├── config.py             # 配置加载，YAML -> dataclass
│   ├── config.example.yaml   # 配置模板
│   ├── config.yaml           # 真实配置（gitignored）
│   ├── database.py           # SQLite 存储，岗位/评分/投递状态
│   ├── ai.py                 # AI 网关对接，评分/填表/总结
│   ├── collectors.py         # 采集器：腾讯文档 MCP / Boss API / 猎聘 API / 网页搜索
│   ├── applicator.py         # 投递引擎，检测表单字段
│   ├── browser_fill.py       # Playwright 浏览器自动填表（基础版）
│   ├── smart_apply.py        # 智能投递：AI 搜索官网 -> Playwright 打开 -> 找入口 -> 填表
│   ├── reporter.py           # Markdown 报告生成
│   ├── web.py                # Flask Web UI，单文件，约 360 行
│   ├── cli.py                # CLI 入口（run/stats/list/approve/reject）
│   └── __init__.py
├── cv.md                     # 简历 Markdown
├── config/
│   ├── profile.yml           # 个人信息（姓名/电话/邮箱/教育/目标岗位）
│   ├── private-application-profile.md  # 网申隐私字段（身份证号等）
│   └── plugins.example.yml
├── voice-dna.md              # AI 写作风格 DNA
├── data/
│   └── agent.db              # SQLite 数据库（gitignored）
├── reports/
│   └── agent/                # 生成的报告（gitignored）
└── .gitignore
```

## 数据流

```
1. 采集（collectors.py）
   腾讯文档 MCP API -> CollectedJob 列表
   Boss 直聘 API -> CollectedJob 列表
   猎聘 API -> CollectedJob 列表

2. 入库去重（database.py）
   CollectedJob -> upsert_job() -> canonical_url 去重

3. AI 评分（ai.py score_job）
   岗位 JD + 简历画像 -> GLM 网关 -> JobScore
   返回：总分、5 个维度分数、匹配点、顾虑、理由
   存入 score_detail 字段（JSON）

4. 智能投递（smart_apply.py）
   公司名 -> AI 搜索网申 URL -> requests 验证可达 ->
   Playwright 打开 -> 检测表单 -> 点击入口按钮 ->
   AI 生成填写内容 -> 逐字段填写 -> 每步截图

5. 人工审核（web.py）
   填表完成后 -> 状态改为 pending_review ->
   用户查看截图 -> approve/reject

6. 报告（reporter.py）
   生成 Markdown 报告 + AI 进度总结
```

## 关键代码路径

### Web UI 启动
```bash
cd /data/home/dorianwu/career-ops
python3 -m agent.web
# 访问 http://127.0.0.1:5000
```

### Agent 运行流程（web.py _run_agent）
- 后台线程执行，_run_state 全局变量跟踪进度
- 前端每秒轮询 /api/run-status 获取实时日志
- 切 Tab 不中断（线程化）

### 智能投递流程（smart_apply.py smart_apply）
1. _search_via_ai(): AI 返回 3-5 个候选 URL
2. _verify_url(): requests.get 验证每个 URL 是否可达
3. _search_baidu(): 如果 AI URL 全不可用，百度搜索
4. Playwright 打开验证通过的 URL
5. 检测 input/textarea/select 表单字段
6. 如果没表单：3 种策略找入口（文字按钮/链接/图片链接）
7. 逐字段填写：先匹配 AI 答案，再通用匹配（name/phone/email/school）
8. 每步截图 base64 编码返回

### AI 评分（ai.py score_job）
- Prompt 要求 AI 返回 5 个维度分数（匹配度/前景/地点/稳定性/薪资）
- 每个维度有原始分、权重、加权分、理由
- 存入 database 的 score_detail 字段（JSON）

## 数据库 Schema

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    jd TEXT DEFAULT '',
    url TEXT NOT NULL,
    canonical_url TEXT UNIQUE,
    score INTEGER DEFAULT 0,
    score_reason TEXT DEFAULT '',
    score_detail TEXT DEFAULT '',  -- JSON: {match_points, concerns, dimensions}
    status TEXT DEFAULT 'new',    -- new/pending_review/applied/rejected
    applied_at TEXT,
    review_status TEXT DEFAULT '',
    review_notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## 下一步任务（按优先级）

### P0: 网申系统自动登录

Moka/zhiye 等系统点"申请职位"后弹出登录框（手机号 + 验证码）。

需要做：
1. 在 config.yaml 加 `login_phone` 字段
2. smart_apply.py 检测到登录框后，自动填入手机号
3. 点击"获取验证码"按钮
4. 前端弹出输入框，用户输入收到的验证码
5. Playwright 填入验证码，点击登录
6. 登录成功后继续填表流程

参考代码（smart_apply.py 里检测表单后加）：
```python
# 检测是否有手机号输入框
phone_input = page.query_selector('input[placeholder*="手机"], input[placeholder*="phone"]')
if phone_input:
    phone_input.fill(profile_data.get('phone', ''))
    # 找验证码按钮
    code_btn = page.get_by_text('获取验证码', exact=False).first
    if code_btn:
        code_btn.click()
        # TODO: 等待用户输入验证码（需要前端交互）
```

### P1: 批量评分加速

当前：893 个岗位 x 3-5 秒/个 = 45-75 分钟

需要做：
1. ai.py 加 `score_batch()` 函数，一次发 10 个岗位给 AI
2. Prompt 格式：给 AI 10 个岗位，返回 10 个评分 JSON
3. _run_agent 里改成每批 10 个调用
4. 预计提速 5-10 倍

### P1: 微信公众号岗位的投递

789 个岗位链接是微信公众号文章，不是网申系统。

当前流程：AI 搜索该公司校招官网 -> Playwright 打开 -> 找入口

问题：AI 找到的 URL 经常不可达（DNS 解析失败），百度搜索被安全验证拦截。

需要做：
1. 改用 Playwright（而非 requests）做百度搜索，绕过安全验证
2. 或者用其他搜索 API（如搜狗）
3. 优先处理 116 个有标准网申链接的岗位

### P2: 前端加载优化

AI 填表需要 60-120 秒，前端只显示转圈。

需要做：
1. /api/preview-apply 改成异步（后台线程 + 轮询）
2. 前端显示进度步骤（"AI 搜索中..." -> "打开浏览器..." -> "检测表单..."）
3. 参考 /api/run 和 /api/run-status 的轮询模式

## 运行环境

- Python 3.11
- Flask（pip install flask）
- Playwright + Chromium（pip install playwright && python3 -m playwright install chromium）
- PyYAML（pip install pyyaml）
- requests（pip install requests）

## 配置

复制 `agent/config.example.yaml` 为 `agent/config.yaml`，填入：

```yaml
ai:
  base_url: "https://your-gateway/v1"
  api_key: "your-key"
  model: "GLM-5.2-TokenHub"

sources:
  tencent_docs:
    enabled: true
    token: "your-tencent-docs-token"
    file_ids: ["your-smartsheet-id"]
```

简历文件已在 career-ops 目录下（cv.md, config/profile.yml 等），自动加载。

## Git

仓库：https://github.com/santifer/career-ops.git
分支：main

agent/ 目录是新代码，career-ops 原有文件不动。

```bash
git add agent/ HANDOFF.md
# 注意不要提交 config.yaml、agent.db 等隐私文件
git commit -m "feat: add job agent with AI scoring and browser auto-apply"
git push
```
