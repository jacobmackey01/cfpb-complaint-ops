from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "CFPB Complaint Operations API"
    api_prefix: str = "/api/v1"
    cfpb_api_url: str = os.getenv(
        "CFPB_API_URL",
        "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/",
    )
    demo_mode: bool = _bool_env(
        "PUBLIC_DEMO_MODE", default=_bool_env("CFPB_DEMO_MODE", default=False)
    )
    allow_demo_fallback: bool = _bool_env("CFPB_ALLOW_DEMO_FALLBACK", default=True)
    live_read_mode: bool = _bool_env("CFPB_LIVE_READ_MODE", default=False)
    openai_model: str = os.getenv(
        "LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    )
    llm_summary_enabled: bool = _bool_env("LLM_SUMMARY_ENABLED", default=False)
    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "ALLOWED_ORIGINS",
            os.getenv("CORS_ORIGINS", "http://localhost:5173"),
        ).split(",")
        if item.strip()
    )
    max_summary_narrative_chars: int = int(
        os.getenv("MAX_SUMMARY_NARRATIVE_CHARS", "12000")
    )


settings = Settings()
