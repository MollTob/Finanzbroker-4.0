"""Die Pipeline-Schritte: ingest -> filter -> score -> push, plus digest."""
from __future__ import annotations

import logging
import sqlite3

from . import db, scoring, telegram
from .config import Config
from .prefilter import is_fresh, is_relevant
from .sources.rss import fetch_feed

log = logging.getLogger(__name__)


def ingest(conn: sqlite3.Connection, cfg: Config, fetch=fetch_feed) -> int:
    new = 0
    for feed in cfg.feeds:
        for item in fetch(feed, cfg.user_agent):
            new += db.insert_article(conn, **item)
    conn.commit()
    log.info("Ingest: %d neue Artikel", new)
    return new


def prefilter(conn: sqlite3.Connection, cfg: Config) -> int:
    """Bewertet neue Artikel und den noch nicht gescorten Rückstau (damit Filteränderungen sofort greifen)."""
    passed = 0
    pending = db.articles_by_status(conn, "new", 100000) + db.articles_by_status(conn, "filtered", 100000)
    for art in pending:
        ok = is_fresh(art["published_at"], cfg.max_age_days) and is_relevant(
            art["title"], art["summary"], art["source_kind"], cfg.keywords, cfg.primary_keywords)
        db.set_status(conn, art["id"], "filtered" if ok else "skipped")
        passed += ok
    conn.commit()
    log.info("Vorfilter: %d Artikel warten auf Scoring", passed)
    return passed


def score(conn: sqlite3.Connection, cfg: Config, scorer=scoring.score_article) -> int:
    if not cfg.llm_api_key:
        log.warning("Kein ANTHROPIC_API_KEY gesetzt, Scoring übersprungen")
        return 0
    created = 0
    for art in db.articles_by_status(conn, "filtered", cfg.max_scoring_per_run):
        try:
            context = db.recent_headlines(conn, art["id"])
            signals = scorer(dict(art), cfg.llm_api_key, cfg.llm_model, context)
        except Exception as exc:  # ein kaputter Artikel darf den Lauf nicht stoppen
            log.warning("Scoring fehlgeschlagen für Artikel %s: %s", art["id"], exc)
            db.set_status(conn, art["id"], "failed")
            conn.commit()
            continue
        for sig in signals:
            db.insert_signal(conn, art["id"], sig)
            created += 1
        db.set_status(conn, art["id"], "scored")
        conn.commit()
    log.info("Scoring: %d Signale", created)
    return created


def push(conn: sqlite3.Connection, cfg: Config, sender=telegram.send) -> int:
    if not (cfg.telegram_token and cfg.telegram_chat_id):
        log.warning("Telegram nicht konfiguriert, Push übersprungen")
        return 0
    sent = 0
    for sig in db.signals_to_push(conn, cfg.push_min_magnitude, cfg.push_min_confidence):
        # Ein Ereignis erzeugt viele Artikel: pro Ziel und Richtung nur ein Push in 24 Stunden.
        if not db.pushed_recently(conn, sig["target"], sig["direction"]):
            sender(cfg.telegram_token, cfg.telegram_chat_id, telegram.format_signal(sig))
            sent += 1
        db.mark(conn, "pushed_at", [sig["id"]])
        conn.commit()
    log.info("Push: %d Nachrichten", sent)
    return sent


def digest(conn: sqlite3.Connection, cfg: Config, title: str = "Digest", sender=telegram.send) -> int:
    if not (cfg.telegram_token and cfg.telegram_chat_id):
        log.warning("Telegram nicht konfiguriert, Digest übersprungen")
        return 0
    signals = db.signals_for_digest(conn, cfg.digest_min_magnitude)
    for message in telegram.format_digest(signals, title):
        sender(cfg.telegram_token, cfg.telegram_chat_id, message)
    db.mark(conn, "digested_at", [s["id"] for s in signals])
    conn.commit()
    log.info("Digest: %d Signale", len(signals))
    return len(signals)


def run(conn: sqlite3.Connection, cfg: Config) -> None:
    ingest(conn, cfg)
    prefilter(conn, cfg)
    score(conn, cfg)
    push(conn, cfg)
