"""AI 网关对接：岗位评分和投递决策。"""

from __future__ import annotations

import json
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class JobScore:
    score: int
    reason: str
    match_points: list[str]
    concerns: list[str]


class AIClient:
    """OpenAI 兼容的 AI 网关客户端。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system: str, user: str, temperature: float = 0.3) -> dict:
        text = self.chat(system, user, temperature)
        # 提取 JSON 块
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: int
    weight: int
    max_score: int
    reason: str


@dataclass(frozen=True)
class JobScore:
    score: int
    reason: str
    match_points: list[str]
    concerns: list[str]
    dimensions: list[DimensionScore]


def score_job(
    client: AIClient,
    profile_text: str,
    job: dict,
    scoring_config: dict,
) -> JobScore:
    """让 AI 对一个岗位打分，返回各维度明细。"""

    weights = scoring_config.get("weights", {})
    city_priority = scoring_config.get("city_priority", [])
    preferred_industries = scoring_config.get("preferred_industries", [])
    exclude_companies = scoring_config.get("exclude_companies", [])

    weight_lines = []
    for k, v in weights.items():
        labels = {
            "match": "候选人匹配度",
            "growth": "工作前景与成长",
            "location": "地点偏好",
            "stability": "公司稳定性",
            "salary": "薪资竞争力",
        }
        weight_lines.append(f"  {k} ({labels.get(k, k)}): 权重 {v}")

    system = """你是一个专业的求职匹配评分系统。根据候选人的简历画像和岗位信息进行评分。

规则：
1. 每个维度打 0-100 分，然后乘以权重百分比得到该维度加权分
2. 总分 = 所有维度加权分之和（满分100）
3. 必须返回每个维度的分数和理由
4. 输出必须是合法 JSON
5. 用中文回答
6. 客观评分，不要为了讨好而虚高"""

    user = f"""## 候选人画像

{profile_text[:3000]}

## 评分维度和权重
{chr(10).join(weight_lines)}

## 城市优先级
{json.dumps(city_priority, ensure_ascii=False)}

## 偏好行业
{json.dumps(preferred_industries, ensure_ascii=False)}

## 排除公司
{json.dumps(exclude_companies, ensure_ascii=False)}

## 待评岗位
- 公司：{job.get('company', '')}
- 岗位：{job.get('title', '')}
- 地点：{job.get('location', '')}
- 薪资：{job.get('salary', '')}
- 岗位描述：{job.get('jd', '')[:1500]}
- 来源：{job.get('source', '')}

请输出 JSON：
```json
{{
  "dimensions": [
    {{"key": "match", "name": "候选人匹配度", "score": 0-100, "weight": 35, "reason": "为什么这个分数"}},
    {{"key": "growth", "name": "工作前景与成长", "score": 0-100, "weight": 15, "reason": "为什么这个分数"}},
    {{"key": "location", "name": "地点偏好", "score": 0-100, "weight": 20, "reason": "为什么这个分数"}},
    {{"key": "stability", "name": "公司稳定性", "score": 0-100, "weight": 15, "reason": "为什么这个分数"}},
    {{"key": "salary", "name": "薪资竞争力", "score": 0-100, "weight": 15, "reason": "为什么这个分数"}}
  ],
  "score": 加权总分,
  "match_points": ["匹配点1", "匹配点2"],
  "concerns": ["顾虑1", "顾虑2"],
  "reason": "一句话总结"
}}
```"""

    result = client.chat_json(system, user)
    dims = []
    for d in result.get("dimensions", []):
        w = d.get("weight", 0)
        s = d.get("score", 0)
        dims.append(DimensionScore(
            name=d.get("name", d.get("key", "")),
            score=s,
            weight=w,
            max_score=int(s * w / 100),
            reason=d.get("reason", ""),
        ))
    return JobScore(
        score=int(result.get("score", 0)),
        reason=result.get("reason", ""),
        match_points=result.get("match_points", []),
        concerns=result.get("concerns", []),
        dimensions=dims,
    )


def generate_application_answers(
    client: AIClient,
    profile_text: str,
    voice_dna: str,
    job: dict,
    form_fields: list[dict],
) -> list[dict]:
    """让 AI 填写网申表单字段。"""

    system = f"""你是一个求职填表助手。根据候选人的信息填写网申表单。

规则：
1. 只填你能确定的字段，不确定的留空
2. 对于开放性问题（如自我介绍、为什么选择我们），用候选人的写作风格回答
3. 输出 JSON 数组，每个元素包含 field_name 和 value
4. 不要编造信息

## 候选人写作风格
{voice_dna}
"""

    user = f"""## 候选人信息

{profile_text}

## 岗位信息
- 公司：{job.get('company', '')}
- 岗位：{job.get('title', '')}
- 岗位描述：{job.get('jd', '')[:1500]}

## 待填表单字段
{json.dumps(form_fields, ensure_ascii=False, indent=2)}

请输出 JSON：
```json
[
  {{"field_name": "字段名", "value": "填写值"}}
]
```"""

    result = client.chat_json(system, user)
    if isinstance(result, list):
        return result
    return result.get("answers", [])


def generate_progress_summary(
    client: AIClient,
    stats: dict,
    recent_jobs: list[dict],
) -> str:
    """让 AI 生成投递进度总结。"""

    system = "你是一个求职进度分析师。根据数据生成简洁的中文总结。"

    user = f"""## 投递数据统计
{json.dumps(stats, ensure_ascii=False, indent=2)}

## 最近岗位列表
{json.dumps(recent_jobs, ensure_ascii=False, indent=2)}

请生成一份简洁的进度总结（200字以内），包括：
1. 已投递/待审核/被拒数量
2. 评分最高的几个岗位
3. 下一步建议"""

    return client.chat(system, user)
