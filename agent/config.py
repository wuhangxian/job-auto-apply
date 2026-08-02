"""加载和验证 Agent 配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AIConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@dataclass
class ProfileConfig:
    cv_md: str = ""
    resume_pdf: str = ""
    profile_yml: str = ""
    application_profile: str = ""
    voice_dna: str = ""


@dataclass
class SourceConfig:
    enabled: bool = False
    token: str = ""
    cookie: str = ""
    file_ids: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    max_results: int = 50


@dataclass
class ScoringConfig:
    min_score: int = 60
    weights: dict[str, int] = field(default_factory=dict)
    city_priority: list[str] = field(default_factory=list)
    preferred_industries: list[str] = field(default_factory=list)
    exclude_companies: list[str] = field(default_factory=list)


@dataclass
class AutoApplyConfig:
    enabled: bool = False
    require_review: bool = True
    batch_size: int = 5
    interval_seconds: int = 30


@dataclass
class OutputConfig:
    reports_dir: str = ""
    database: str = ""


@dataclass
class AgentConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    auto_apply: AutoApplyConfig = field(default_factory=AutoApplyConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    root_dir: Path = field(default_factory=lambda: Path.cwd())


def load_config(config_path: str | Path) -> AgentConfig:
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    root = path.parent
    config = AgentConfig(root_dir=root)

    ai_raw = raw.get("ai", {})
    config.ai = AIConfig(
        base_url=ai_raw.get("base_url", ""),
        api_key=ai_raw.get("api_key", ""),
        model=ai_raw.get("model", ""),
    )

    profile_raw = raw.get("profile", {})
    config.profile = ProfileConfig(
        cv_md=str((root / profile_raw.get("cv_md", "")).resolve()) if profile_raw.get("cv_md") else "",
        resume_pdf=profile_raw.get("resume_pdf", ""),
        profile_yml=str((root / profile_raw.get("profile_yml", "")).resolve()) if profile_raw.get("profile_yml") else "",
        application_profile=str((root / profile_raw.get("application_profile", "")).resolve()) if profile_raw.get("application_profile") else "",
        voice_dna=str((root / profile_raw.get("voice_dna", "")).resolve()) if profile_raw.get("voice_dna") else "",
    )

    sources_raw = raw.get("sources", {})
    for name, src in sources_raw.items():
        config.sources[name] = SourceConfig(
            enabled=src.get("enabled", False),
            token=src.get("token", ""),
            cookie=src.get("cookie", ""),
            file_ids=src.get("file_ids", []),
            tables=src.get("tables", []),
            keywords=src.get("keywords", []),
            cities=src.get("cities", []),
            max_results=src.get("max_results", 50),
        )

    scoring_raw = raw.get("scoring", {})
    config.scoring = ScoringConfig(
        min_score=scoring_raw.get("min_score", 60),
        weights=scoring_raw.get("weights", {"match": 35, "growth": 15, "location": 20, "stability": 15, "salary": 15}),
        city_priority=scoring_raw.get("city_priority", []),
        preferred_industries=scoring_raw.get("preferred_industries", []),
        exclude_companies=scoring_raw.get("exclude_companies", []),
    )

    apply_raw = raw.get("auto_apply", {})
    config.auto_apply = AutoApplyConfig(
        enabled=apply_raw.get("enabled", False),
        require_review=apply_raw.get("require_review", True),
        batch_size=apply_raw.get("batch_size", 5),
        interval_seconds=apply_raw.get("interval_seconds", 30),
    )

    output_raw = raw.get("output", {})
    config.output = OutputConfig(
        reports_dir=str((root / output_raw.get("reports_dir", "reports")).resolve()),
        database=str((root / output_raw.get("database", "data/agent.db")).resolve()),
    )

    return config


def load_profile_text(config: AgentConfig) -> str:
    """加载简历和个人信息，组装成 AI prompt 可用的文本。"""
    parts = []
    if config.profile.cv_md and Path(config.profile.cv_md).exists():
        parts.append(Path(config.profile.cv_md).read_text(encoding="utf-8"))
    if config.profile.profile_yml and Path(config.profile.profile_yml).exists():
        parts.append(Path(config.profile.profile_yml).read_text(encoding="utf-8"))
    if config.profile.application_profile and Path(config.profile.application_profile).exists():
        parts.append(Path(config.profile.application_profile).read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)
