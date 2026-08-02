#!/usr/bin/env python3
"""求职 Agent CLI：一条命令跑完采集→评分→投递→报告。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中
_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from agent.config import load_config, load_profile_text
from agent.database import Database
from agent.ai import AIClient, score_job, generate_progress_summary
from agent.collectors import (
    CollectedJob,
    collect_tencent_docs,
    collect_boss,
    collect_liepin,
    collect_web,
)
from agent.applicator import Applicator
from agent.reporter import generate_report, save_report


def cmd_run(args):
    """完整流程：采集 → 评分 → 投递 → 报告。"""

    config = load_config(args.config)
    db = Database(config.output.database)

    profile_text = load_profile_text(config)
    if not profile_text:
        print("错误: 无法加载个人信息，请检查 profile 配置")
        return 1

    if not config.ai.api_key:
        print("错误: AI 网关 API Key 未配置")
        return 1

    ai = AIClient(config.ai.base_url, config.ai.api_key, config.ai.model)

    # === 1. 采集 ===
    print("=== 1. 采集岗位 ===")
    all_jobs: list[CollectedJob] = []

    sources = config.sources

    if sources.get("tencent_docs") and sources["tencent_docs"].enabled and sources["tencent_docs"].token:
        print("  腾讯文档采集中...")
        try:
            jobs = collect_tencent_docs(
                sources["tencent_docs"].token,
                sources["tencent_docs"].file_ids,
                sources["tencent_docs"].tables or None,
                progress=lambda n: print(f"    已采集 {n} 条"),
            )
            print(f"    腾讯文档完成: {len(jobs)} 条")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"    腾讯文档失败: {e}")

    if sources.get("boss") and sources["boss"].enabled and sources["boss"].token:
        print("  Boss 直聘搜索中...")
        try:
            jobs = collect_boss(
                sources["boss"].token,
                sources["boss"].keywords,
                sources["boss"].cities,
                sources["boss"].max_results,
                progress=lambda n: print(f"    已找到 {n} 条"),
            )
            print(f"    Boss 直聘完成: {len(jobs)} 条")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"    Boss 直聘失败: {e}")

    if sources.get("liepin") and sources["liepin"].enabled and sources["liepin"].cookie:
        print("  猎聘搜索中...")
        try:
            jobs = collect_liepin(
                sources["liepin"].cookie,
                sources["liepin"].keywords,
                sources["liepin"].cities,
                sources["liepin"].max_results,
                progress=lambda n: print(f"    已找到 {n} 条"),
            )
            print(f"    猎聘完成: {len(jobs)} 条")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"    猎聘失败: {e}")

    if sources.get("web") and sources["web"].enabled:
        print("  网页搜索中...")
        try:
            jobs = collect_web(
                sources["web"].keywords,
                progress=lambda n: print(f"    已找到 {n} 条"),
            )
            print(f"    网页搜索完成: {len(jobs)} 条")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"    网页搜索失败: {e}")

    if not all_jobs:
        print("  未采集到任何岗位。请检查信息源配置。")
        return 0

    print(f"  总计采集: {len(all_jobs)} 条")

    # === 2. 入库 ===
    print("=== 2. 入库去重 ===")
    new_count = 0
    for job in all_jobs:
        job_id = db.upsert_job(
            source=job.source,
            company=job.company,
            title=job.title,
            url=job.url,
            location=job.location,
            salary=job.salary,
            jd=job.jd,
        )
        if job_id:
            new_count += 1
    print(f"  新增/更新: {new_count} 条")

    # === 3. AI 评分 ===
    print("=== 3. AI 评分 ===")
    unscored = db.list_jobs(min_score=0, limit=100)
    unscored = [j for j in unscored if j.score == 0]
    print(f"  待评分: {len(unscored)} 条")

    scoring_config = {
        "weights": config.scoring.weights,
        "city_priority": config.scoring.city_priority,
        "preferred_industries": config.scoring.preferred_industries,
        "exclude_companies": config.scoring.exclude_companies,
    }

    for i, job in enumerate(unscored):
        try:
            print(f"  [{i+1}/{len(unscored)}] {job.company} - {job.title}...", end=" ")
            job_dict = {
                "company": job.company,
                "title": job.title,
                "location": job.location,
                "salary": job.salary,
                "jd": job.jd,
                "source": job.source,
            }
            result = score_job(ai, profile_text, job_dict, scoring_config)
            db.set_score(job.id, result.score, result.reason)
            print(f"{result.score}分 - {result.reason}")
        except Exception as e:
            print(f"评分失败: {e}")
            db.set_score(job.id, 1, f"评分失败: {e}")

    # === 4. 自动投递 ===
    if config.auto_apply.enabled:
        print("=== 4. 自动投递 ===")
        voice_dna = ""
        if config.profile.voice_dna and Path(config.profile.voice_dna).exists():
            voice_dna = Path(config.profile.voice_dna).read_text(encoding="utf-8")

        applicator = Applicator(
            ai, profile_text, voice_dna,
            require_review=config.auto_apply.require_review,
        )

        candidates = db.get_unapplied_high_score(limit=config.auto_apply.batch_size)
        print(f"  高分候选: {len(candidates)} 个")

        for i, job in enumerate(candidates):
            if job.score < config.scoring.min_score:
                continue
            print(f"  [{i+1}] {job.company} - {job.title} ({job.score}分)")
            try:
                result = applicator.apply_to_job({
                    "id": job.id,
                    "company": job.company,
                    "title": job.title,
                    "url": job.url,
                    "jd": job.jd,
                })
                print(f"    {result.message}")
                if result.submitted:
                    db.mark_applied(job.id)
                elif result.success:
                    db.set_status(job.id, "pending_review")
                    db.set_review(job.id, "pending", result.message)
                time.sleep(config.auto_apply.interval_seconds)
            except Exception as e:
                print(f"    投递失败: {e}")
    else:
        print("=== 4. 自动投递 (已禁用) ===")

    # === 5. 报告 ===
    print("=== 5. 生成报告 ===")
    stats = db.stats()
    all_scored = db.list_jobs(min_score=0, limit=500)

    ai_summary = ""
    try:
        recent = [
            {"company": j.company, "title": j.title, "score": j.score, "status": j.status}
            for j in all_scored[:20]
        ]
        ai_summary = generate_progress_summary(ai, stats, recent)
    except Exception:
        pass

    report = generate_report(all_scored, stats, ai_summary)
    report_path = save_report(report, config.output.reports_dir)
    print(f"  报告已保存: {report_path}")
    print()
    print("=== 完成 ===")
    print(f"采集 {stats['total']} 个岗位，已投递 {stats['applied']} 个，待审核 {stats['pending_review']} 个")
    if stats['high_score_unapplied'] > 0:
        print(f"还有 {stats['high_score_unapplied']} 个高分岗位等你审核")
    return 0


def cmd_review(args):
    """查看待审核的投递。"""

    config = load_config(args.config)
    db = Database(config.output.database)

    pending = db.list_jobs(status="pending_review", limit=50)
    if not pending:
        print("没有待审核的投递")
        return 0

    print(f"待审核投递 ({len(pending)} 个):\n")
    for job in pending:
        print(f"[{job.id}] {job.score}分 | {job.company} - {job.title}")
        print(f"    地点: {job.location} | 薪资: {job.salary} | 来源: {job.source}")
        print(f"    链接: {job.url}")
        print(f"    审核备注: {job.review_notes}")
        print()

    print("操作: python -m agent.cli approve <id>  - 确认提交")
    print("      python -m agent.cli reject <id>   - 拒绝")
    return 0


def cmd_stats(args):
    """查看进度统计。"""

    config = load_config(args.config)
    db = Database(config.output.database)
    stats = db.stats()

    print("=== 求职进度 ===")
    print(f"  采集岗位总数:  {stats['total']}")
    print(f"  已投递:        {stats['applied']}")
    print(f"  待审核:        {stats['pending_review']}")
    print(f"  被拒:          {stats['rejected']}")
    print(f"  高分未投(>=70): {stats['high_score_unapplied']}")

    top_jobs = db.list_jobs(min_score=70, limit=5)
    if top_jobs:
        print("\n=== Top 5 岗位 ===")
        for job in top_jobs:
            print(f"  [{job.id}] {job.score}分 | {job.company} - {job.title} ({job.location})")
    return 0


def cmd_approve(args):
    """确认提交一个投递。"""

    config = load_config(args.config)
    db = Database(config.output.database)
    db.mark_applied(args.job_id)
    db.set_review(args.job_id, "approved", "用户确认提交")
    print(f"岗位 {args.job_id} 已标记为已投递")
    return 0


def cmd_reject(args):
    """拒绝一个投递。"""

    config = load_config(args.config)
    db = Database(config.output.database)
    db.set_status(args.job_id, "rejected")
    db.set_review(args.job_id, "rejected", "用户拒绝")
    print(f"岗位 {args.job_id} 已拒绝")
    return 0


def cmd_list(args):
    """列出岗位。"""

    config = load_config(args.config)
    db = Database(config.output.database)

    min_score = args.min_score if args.min_score else 0
    status = args.status if args.status else None

    jobs = db.list_jobs(status=status, min_score=min_score, limit=args.limit)
    if not jobs:
        print("没有找到岗位")
        return 0

    print(f"岗位列表 ({len(jobs)} 个, 评分 >= {min_score}):\n")
    for job in jobs:
        status_icon = {
            "new": "🆕", "applied": "✅", "pending_review": "⏳",
            "rejected": "❌",
        }.get(job.status, "  ")
        print(f"  {status_icon} [{job.id}] {job.score}分 | {job.company} - {job.title} | {job.location} | {job.source}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="求职 Agent：采集 → AI 评分 → 自动投递 → 进度看板",
    )
    parser.add_argument("--config", default="agent/config.yaml", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run", help="运行完整流程")
    subparsers.add_parser("review", help="查看待审核投递")
    subparsers.add_parser("stats", help="查看进度统计")
    list_parser = subparsers.add_parser("list", help="列出岗位")
    list_parser.add_argument("--status", choices=["new", "applied", "pending_review", "rejected"], default=None)
    list_parser.add_argument("--min-score", type=int, default=0)
    list_parser.add_argument("--limit", type=int, default=50)

    approve_parser = subparsers.add_parser("approve", help="确认提交投递")
    approve_parser.add_argument("job_id", type=int)

    reject_parser = subparsers.add_parser("reject", help="拒绝投递")
    reject_parser.add_argument("job_id", type=int)

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "review":
        sys.exit(cmd_review(args))
    elif args.command == "stats":
        sys.exit(cmd_stats(args))
    elif args.command == "list":
        sys.exit(cmd_list(args))
    elif args.command == "approve":
        sys.exit(cmd_approve(args))
    elif args.command == "reject":
        sys.exit(cmd_reject(args))


if __name__ == "__main__":
    main()
