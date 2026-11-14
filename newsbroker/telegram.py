"""Telegram-Ausgabe: Sofort-Push für starke Signale, Digest für den Rest."""
from __future__ import annotations

import html

import requests

ARROW = {"long": "🟢 LONG", "short": "🔴 SHORT", "neutral": "⚪ NEUTRAL"}
MAX_LEN = 4000  # Telegram-Limit liegt bei 4096 Zeichen


class TelegramError(RuntimeError):
    """Fehler der Telegram-API. Die Meldung enthält bewusst keine URL, weil darin das Token steht."""


def _call(method: str, token: str, timeout: int, **kwargs) -> dict:
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN fehlt in der .env")
    try:
        resp = requests.request(
            "POST" if "json" in kwargs else "GET",
            f"https://api.telegram.org/bot{token}/{method}", timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise TelegramError(f"Telegram nicht erreichbar ({type(exc).__name__})") from None
    if resp.status_code == 401:
        raise TelegramError("Telegram lehnt das Token ab (401). TELEGRAM_BOT_TOKEN in der .env prüfen.")
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.ok or not data.get("ok", False):
        raise TelegramError(f"Telegram-Fehler {resp.status_code}: {data.get('description', 'unbekannt')}")
    return data


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
    if not chat_id:
        raise TelegramError("TELEGRAM_CHAT_ID fehlt in der .env")
    _call("sendMessage", token, timeout,
          json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})


def find_chat_ids(token: str, timeout: int = 20) -> list[tuple[int, str]]:
    """Liest aus getUpdates, wer dem Bot geschrieben hat: Liste aus (Chat-ID, Name)."""
    chats = {}
    for update in _call("getUpdates", token, timeout).get("result", []):
        chat = (update.get("message") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("first_name") or chat.get("title") or ""
    return list(chats.items())
