"""Telegram-Ausgabe: Sofort-Push für starke Signale, Digest für den Rest."""
from __future__ import annotations

import html

import requests

ARROW = {"long": "🟢 LONG", "short": "🔴 SHORT", "neutral": "⚪ NEUTRAL"}
MAX_LEN = 4000  # Telegram-Limit liegt bei 4096 Zeichen


def format_signal(sig) -> str:
    esc = html.escape
    lines = [
        f"<b>{ARROW[sig['direction']]} {esc(sig['target'])}</b> ({esc(sig['region'])}, {esc(sig['level'])})",
        f"Stärke {sig['magnitude']}/5 · Konfidenz {sig['confidence']:.0%} · Horizont: {esc(sig['horizon'])}",
        esc(sig["rationale"]),
    ]
    if sig["invalidation"]:
        lines.append(f"<i>Widerlegt durch:</i> {esc(sig['invalidation'])}")
    if sig["related"]:
        lines.append(f"<i>Auch betroffen:</i> {esc(sig['related'])}")
    lines.append(f'<a href="{esc(sig["article_url"], quote=True)}">{esc(sig["article_source"])}: {esc(sig["article_title"])}</a>')
    return "\n".join(lines)


def format_digest(signals, title: str = "Digest") -> list[str]:
    """Baut Digest-Nachrichten und teilt sie unterhalb des Telegram-Limits auf."""
    if not signals:
        return []
    messages, current = [], f"<b>{html.escape(title)}</b> ({len(signals)} Signale)"
    for sig in signals:
        block = format_signal(sig)
        if len(current) + len(block) + 2 > MAX_LEN:
            messages.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}"
    messages.append(current)
    return messages


def send(token: str, chat_id: str, text: str, timeout: int = 20) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=timeout,
    )
    resp.raise_for_status()
