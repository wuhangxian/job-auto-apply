"""生成岗位报告和进度看板。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def generate_report(jobs: list, stats: dict, ai_summary: str = "") -> str:
    """生成 Markdown 格式的岗位推荐报告。"""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 求职 Agent 报告 - {now}",
        "",
        "## 概览",
        "",
        f"- 采集岗位总数: {stats.get('total', 0)}",
        f"- 已投递: {stats.get('applied', 0)}",
        f"- 待审核: {stats.get('pending_review', 0)}",
        f"- 被拒: {stats.get('rejected', 0)}",
        f"- 高分未投 (>= 70): {stats.get('high_score_unapplied', 0)}",
        "",
    ]

    if ai_summary:
        lines.extend(["## AI 进度总结", "", ai_summary, ""])

    high_score = [j for j in jobs if j.score >= 70]
    medium_score = [j for j in jobs if 50 <= j.score < 70]
    low_score = [j for j in jobs if 0 < j.score < 50]

    if high_score:
        lines.extend(["## 推荐投递 (评分 >= 70)", ""])
        lines.append("| 分数 | 公司 | 岗位 | 地点 | 薪资 | 来源 | 状态 |")
        lines.append("|------|------|------|------|------|------|------|")
        for job in high_score:
            lines.append(
                f"| {job.score} | {job.company} | {job.title} | {job.location} | {job.salary} | {job.source} | {job.status} |"
            )
        lines.append("")

    if medium_score:
        lines.extend(["## 可考虑 (50-69)", ""])
        lines.append("| 分数 | 公司 | 岗位 | 地点 | 来源 |")
        lines.append("|------|------|------|------|------|")
        for job in medium_score[:20]:
            lines.append(
                f"| {job.score} | {job.company} | {job.title} | {job.location} | {job.source} |"
            )
        lines.append("")

    if high_score:
        lines.extend(["## 评分详情", ""])
        for job in high_score[:10]:
            lines.append(f"### {job.company} - {job.title} ({job.score}分)")
            lines.append(f"- 链接: {job.url}")
            lines.append(f"- 理由: {job.score_reason}")
            lines.append("")

    return "\n".join(lines)


def save_report(report: str, reports_dir: str) -> str:
    """保存报告到文件，返回路径。"""

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = reports_path / f"report_{date_str}.md"
    path.write_text(report, encoding="utf-8")
    return str(path)
