"""Billiger Vorfilter vor dem LLM: nur frische Artikel mit Markt-Relevanz kosten Tokens."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def is_relevant(title: str, summary: str, source_kind: str, keywords: list[str],
                primary_keywords: list[str]) -> bool:
    """Keyword-Treffer in Titel oder Zusammenfassung. Primärquellen haben eine eigene, engere Liste,
    weil ihre Feeds viel Verwaltungsrauschen enthalten (Genehmigungen, Fristen, Reden ohne Inhalt)."""
    text = f" {title} {summary} ".lower()
    words = primary_keywords if source_kind == "primary" else keywords
    return any(k in text for k in words)


def is_fresh(published_at: Optional[str], max_age_days: int, now: Optional[datetime] = None) -> bool:
    """Artikel ohne Datum gelten als frisch. Alte Feed-Historie soll kein Scoring-Budget fressen."""
    if not published_at:
        return True
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
    return published_at >= cutoff.isoformat(timespec="seconds")
