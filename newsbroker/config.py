"""Konfiguration: Secrets aus .env / Umgebung, Feeds und Keywords aus TOML."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.9/3.10 (z. B. das System-Python von macOS)
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    """Liest KEY=VALUE-Zeilen aus .env, ohne bestehende Umgebungswerte zu überschreiben."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Feed:
    name: str
    url: str
    kind: str = "media"  # "primary" (Behörde/Börse) oder "media"
    region: str = "global"


@dataclass
class Config:
    db_path: Path
    feeds: list[Feed]
    keywords: list[str]
    primary_keywords: list[str]
    user_agent: str
    llm_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    push_min_magnitude: int = 4
    push_min_confidence: float = 0.7
    digest_min_magnitude: int = 2
    max_scoring_per_run: int = 25
    max_age_days: int = 3
    extra: dict = field(default_factory=dict)


def load_config(root: Path = ROOT) -> Config:
    load_env(root / ".env")
    with open(root / "config" / "feeds.toml", "rb") as fh:
        data = tomllib.load(fh)
    settings = data.get("settings", {})
    return Config(
        db_path=Path(os.environ.get("NEWSBROKER_DB", root / "data" / "newsbroker.db")),
        feeds=[Feed(**f) for f in data.get("feeds", [])],
        keywords=[k.lower() for k in data.get("keywords", [])],
        primary_keywords=[k.lower() for k in data.get("primary_keywords", [])],
        user_agent=os.environ.get("NEWSBROKER_USER_AGENT", "Finanzbroker/4.0 (privat)"),
        llm_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        llm_model=os.environ.get("NEWSBROKER_LLM_MODEL", settings.get("llm_model", "claude-haiku-5-5")),
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        push_min_magnitude=settings.get("push_min_magnitude", 4),
        push_min_confidence=settings.get("push_min_confidence", 0.7),
        digest_min_magnitude=settings.get("digest_min_magnitude", 2),
        max_scoring_per_run=settings.get("max_scoring_per_run", 25),
        max_age_days=settings.get("max_age_days", 3),
    )
