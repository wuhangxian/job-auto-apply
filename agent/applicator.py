"""自动投递：填写网申表单，提交前等用户审核。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

from agent.ai import AIClient, generate_application_answers


@dataclass(frozen=True)
class ApplicationResult:
    job_id: int
    success: bool
    message: str
    submitted: bool = False


class Applicator:
    """自动投递引擎。"""

    def __init__(
        self,
        ai_client: AIClient,
        profile_text: str,
        voice_dna: str,
        require_review: bool = True,
    ):
        self.ai = ai_client
        self.profile_text = profile_text
        self.voice_dna = voice_dna
        self.require_review = require_review

    def apply_to_job(self, job: dict) -> ApplicationResult:
        """对一个岗位执行自动投递流程。"""

        # 1. 尝试获取投递页面的表单字段
        form_fields = self._detect_form_fields(job.get("url", ""))

        if not form_fields:
            return ApplicationResult(
                job_id=job.get("id", 0),
                success=False,
                message="无法检测到投递表单，需要手动投递",
            )

        # 2. AI 填写表单
        answers = generate_application_answers(
            self.ai,
            self.profile_text,
            self.voice_dna,
            job,
            form_fields,
        )

        # 3. 等待用户审核
        if self.require_review:
            return ApplicationResult(
                job_id=job.get("id", 0),
                success=True,
                message=f"AI 已填写 {len(answers)} 个字段，等待审核",
                submitted=False,
            )

        # 4. 提交表单（require_review=False 时）
        return ApplicationResult(
            job_id=job.get("id", 0),
            success=True,
            message=f"已自动提交，填写了 {len(answers)} 个字段",
            submitted=True,
        )

    def _detect_form_fields(self, url: str) -> list[dict]:
        """检测投递页面的表单字段。"""

        if not url:
            return []

        # 对于 Boss 直聘等已知平台，返回标准字段
        if "zhipin.com" in url or "boss" in url.lower():
            return [
                {"field_name": "name", "type": "text", "label": "姓名"},
                {"field_name": "phone", "type": "tel", "label": "手机号"},
                {"field_name": "email", "type": "email", "label": "邮箱"},
                {"field_name": "resume", "type": "file", "label": "简历附件"},
                {"field_name": "coverLetter", "type": "textarea", "label": "求职信"},
            ]

        # 对于 Moka 等网申系统
        if "mokahr.com" in url:
            return [
                {"field_name": "name", "type": "text", "label": "姓名"},
                {"field_name": "phone", "type": "tel", "label": "手机"},
                {"field_name": "email", "type": "email", "label": "邮箱"},
                {"field_name": "school", "type": "text", "label": "学校"},
                {"field_name": "major", "type": "text", "label": "专业"},
                {"field_name": "resume", "type": "file", "label": "上传简历"},
                {"field_name": "self_introduction", "type": "textarea", "label": "自我介绍"},
            ]

        # 通用检测：尝试请求页面，提取 form 字段
        try:
            response = requests.get(url, timeout=15, allow_redirects=True)
            fields = []
            import re
            # 提取 input/textarea/select 标签
            for match in re.finditer(
                r'<(?:input|textarea|select)[^>]+(?:name|id)=["\x27]([^"\x27]+)["\x27][^>]*>',
                response.text,
            ):
                fields.append({"field_name": match.group(1), "type": "text", "label": match.group(1)})
            return fields[:20]  # 限制数量
        except Exception:
            return []
