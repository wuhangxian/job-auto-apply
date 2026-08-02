# 求职 Agent

全自动求职投递 Agent：采集岗位 -> AI 评分 -> 浏览器自动填表 -> 人工审核 -> 进度看板。

## 快速开始

```bash
# 1. 安装依赖
pip install flask pyyaml requests playwright
python3 -m playwright install chromium

# 2. 配置
cp agent/config.example.yaml agent/config.yaml
# 编辑 config.yaml 填入 AI API Key 和信息源 token

# 3. 启动 Web UI
python3 -m agent.web
# 浏览器打开 http://127.0.0.1:5000

# 4. 或用 CLI
python3 -m agent.cli run       # 采集 -> 评分 -> 报告
python3 -m agent.cli stats    # 查看进度
python3 -m agent.cli list      # 岗位列表
python3 -m agent.cli review   # 待审核投递
```

## 功能

| 功能 | 状态 |
|------|------|
| 腾讯文档岗位采集 | ✅ |
| Boss 直聘采集 | ⚠️ 需填 token |
| 猎聘采集 | ⚠️ 需填 cookie |
| AI 评分（5 维度明细） | ✅ |
| Playwright 浏览器自动填表 | ✅ |
| 智能搜索公司校招官网 | ✅ |
| Web UI（看板/列表/审核/配置） | ✅ |
| 后台运行 + 实时日志 | ✅ |
| 网申系统自动登录 | ❌ 待开发 |

## 配置说明

见 `agent/config.example.yaml`，主要配置项：

- `ai.base_url` / `ai.api_key` / `ai.model` — AI 网关（OpenAI 兼容）
- `sources.tencent_docs` — 腾讯文档 SmartSheet 信息源
- `sources.boss` — Boss 直聘（wt2 token）
- `sources.liepin` — 猎聘（cookie）
- `scoring` — 评分规则（权重/城市偏好/行业偏好）
- `auto_apply` — 自动投递设置

## 交接文档

详细架构、数据流、下一步任务见 `agent/HANDOFF.md`。
