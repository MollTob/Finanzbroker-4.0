"""SQLite-Schema und Zugriffe. Der Signal-Log ist die Basis für die spätere Auswertung."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY,
    source       TEXT NOT NULL,
    source_kind  TEXT NOT NULL,
    region       TEXT NOT NULL,
    url          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    title_hash   TEXT NOT NULL UNIQUE,
    published_at TEXT,
    fetched_at   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new'   -- new | filtered | scored | failed
);
CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY,
    article_id   INTEGER NOT NULL REFERENCES articles(id),
    created_at   TEXT NOT NULL,
    level        TEXT NOT NULL,     -- titel | segment | makro
    target       TEXT NOT NULL,     -- Ticker, Segment oder Markt
    region       TEXT NOT NULL,
    direction    TEXT NOT NULL,     -- long | short | neutral
    magnitude    INTEGER NOT NULL,  -- 1..5
    horizon      TEXT NOT NULL,     -- tage | woche
    confidence   REAL NOT NULL,     -- 0..1
    surprise     INTEGER NOT NULL,  -- 1..5
    rationale    TEXT NOT NULL,
    invalidation TEXT NOT NULL DEFAULT '',
    related      TEXT NOT NULL DEFAULT '',
    pushed_at    TEXT,
    digested_at  TEXT
);
CREATE TABLE IF NOT EXISTS evaluations (
    signal_id  INTEGER NOT NULL REFERENCES signals(id),
    days       INTEGER NOT NULL,
    price_ref  REAL,
    price_then REAL,
    return_pct REAL,
    PRIMARY KEY (signal_id, days)
);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def title_hash(title: str) -> str:
    """Normalisierter Titel-Hash, damit dieselbe Meldung von mehreren Feeds nur einmal landet."""
    norm = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_article(conn: sqlite3.Connection, *, source: str, source_kind: str, region: str,
                   url: str, title: str, summary: str, published_at: str | None) -> bool:
    """Fügt einen Artikel ein. Gibt False zurück, wenn URL oder Titel schon bekannt sind."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO articles (source, source_kind, region, url, title, summary,"
        " title_hash, published_at, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (source, source_kind, region, url, title, summary, title_hash(title), published_at, now_iso()),
    )
    return cur.rowcount == 1


def articles_by_status(conn: sqlite3.Connection, status: str, limit: int = 1000) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM articles WHERE status = ? ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC LIMIT ?",
        (status, limit),
    ).fetchall()


def set_status(conn: sqlite3.Connection, article_id: int, status: str) -> None:
    conn.execute("UPDATE articles SET status = ? WHERE id = ?", (status, article_id))


def insert_signal(conn: sqlite3.Connection, article_id: int, sig: dict) -> int:
    cur = conn.execute(
        "INSERT INTO signals (article_id, created_at, level, target, region, direction, magnitude,"
        " horizon, confidence, surprise, rationale, invalidation, related)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (article_id, now_iso(), sig["level"], sig["target"], sig["region"], sig["direction"],
         sig["magnitude"], sig["horizon"], sig["confidence"], sig["surprise"], sig["rationale"],
         sig["invalidation"], ", ".join(sig["related"])),
    )
    return cur.lastrowid


SIGNAL_JOIN = (
    "SELECT s.*, a.title AS article_title, a.url AS article_url, a.source AS article_source"
    " FROM signals s JOIN articles a ON a.id = s.article_id "
)


def signals_to_push(conn: sqlite3.Connection, min_magnitude: int, min_confidence: float) -> list[sqlite3.Row]:
    return conn.execute(
        SIGNAL_JOIN + "WHERE s.pushed_at IS NULL AND s.direction != 'neutral'"
        " AND s.magnitude >= ? AND s.confidence >= ? ORDER BY s.magnitude DESC, s.id",
        (min_magnitude, min_confidence),
    ).fetchall()


def signals_for_digest(conn: sqlite3.Connection, min_magnitude: int) -> list[sqlite3.Row]:
    return conn.execute(
        SIGNAL_JOIN + "WHERE s.digested_at IS NULL AND s.direction != 'neutral' AND s.magnitude >= ?"
        " ORDER BY s.magnitude DESC, s.confidence DESC, s.id",
        (min_magnitude,),
    ).fetchall()


def mark(conn: sqlite3.Connection, column: str, signal_ids: list[int]) -> None:
    assert column in ("pushed_at", "digested_at")
    conn.executemany(f"UPDATE signals SET {column} = ? WHERE id = ?", [(now_iso(), i) for i in signal_ids])


def retry_failed(conn: sqlite3.Connection) -> int:
    """Setzt fehlgeschlagene Artikel zurück, damit der nächste Lauf sie erneut bewertet."""
    cur = conn.execute("UPDATE articles SET status = 'filtered' WHERE status = 'failed'")
    conn.commit()
    return cur.rowcount
