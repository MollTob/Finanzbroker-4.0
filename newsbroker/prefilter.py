"""Billiger Vorfilter vor dem LLM: nur Artikel mit Markt-Relevanz kosten Tokens."""
from __future__ import annotations


def is_relevant(title: str, summary: str, source_kind: str, keywords: list[str]) -> bool:
    """Primärquellen gehen immer durch, Medienartikel nur bei Keyword-Treffer."""
    if source_kind == "primary":
        return True
    text = f"{title} {summary}".lower()
    return any(k in text for k in keywords)
