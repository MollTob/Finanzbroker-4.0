"""RSS/Atom-Adapter. Deckt Medien-Feeds und offizielle Feeds (SEC, Notenbanken) ab."""
from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

from ..config import Feed

log = logging.getLogger(__name__)
TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str, limit: int = 600) -> str:
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def parse_feed(raw: bytes | str, feed: Feed) -> list[dict]:
    """Wandelt Feed-Inhalt in Artikel-Dicts um (ohne Netzwerk, daher testbar)."""
    parsed = feedparser.parse(raw)
    items = []
    for entry in parsed.entries:
        title = clean(entry.get("title", ""), 300)
        url = entry.get("link", "")
        if not title or not url:
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = (
            datetime.fromtimestamp(time.mktime(stamp), tz=timezone.utc).isoformat(timespec="seconds")
            if stamp else None
        )
        items.append({
            "source": feed.name, "source_kind": feed.kind, "region": feed.region,
            "url": url, "title": title, "summary": clean(entry.get("summary", "")),
            "published_at": published,
        })
    return items


def fetch_feed(feed: Feed, user_agent: str, timeout: int = 20) -> list[dict]:
    """Lädt einen Feed. Fehler werden geloggt und führen zu einer leeren Liste, nicht zum Abbruch."""
    try:
        resp = requests.get(feed.url, headers={"User-Agent": user_agent}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Feed %s nicht erreichbar: %s", feed.name, exc)
        return []
    return parse_feed(resp.content, feed)
