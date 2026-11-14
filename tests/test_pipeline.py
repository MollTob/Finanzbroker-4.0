from pathlib import Path

import pytest

from newsbroker import db, pipeline, scoring, telegram
from newsbroker.config import Config, Feed
from datetime import datetime, timezone

from newsbroker.prefilter import is_fresh, is_relevant
from newsbroker.sources.rss import parse_feed

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Nvidia CEO steps down amid probe</title><link>https://example.com/a</link>
<description>&lt;p&gt;Shares fall.&lt;/p&gt;</description><pubDate>Sat, 14 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Local bakery wins award</title><link>https://example.com/b</link><description>Nice bread.</description></item>
</channel></rss>"""

FEED = Feed(name="Test", url="https://example.com/rss", kind="media", region="US")

LLM_REPLY = """Hier das Ergebnis:
{"signals": [{"level": "titel", "target": "NVDA", "region": "US", "direction": "short",
"magnitude": 5, "horizon": "tage", "confidence": 0.8, "surprise": 5,
"rationale": "CEO-Abgang mit Ermittlung.", "invalidation": "Dementi", "related": ["AMD", "TSMC"]},
{"level": "quatsch", "target": "X", "direction": "long"}]}"""


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.fixture
def cfg():
    return Config(db_path=Path(":memory:"), feeds=[FEED], keywords=["ceo", "steps down"], primary_keywords=["fomc"], max_age_days=100000,
                  user_agent="test", llm_api_key="k", telegram_token="t", telegram_chat_id="c")


def test_parse_feed_cleans_html():
    items = parse_feed(RSS, FEED)
    assert len(items) == 2
    assert items[0]["summary"] == "Shares fall."
    assert items[0]["published_at"].startswith("2026-11-14")


def test_dedup_by_url_and_title(conn):
    item = parse_feed(RSS, FEED)[0]
    assert db.insert_article(conn, **item) is True
    assert db.insert_article(conn, **item) is False
    same_title = {**item, "url": "https://other.example/x", "title": "NVIDIA CEO steps down, amid probe!"}
    assert db.insert_article(conn, **same_title) is False


def test_prefilter():
    assert is_relevant("Nvidia CEO steps down", "", "media", ["ceo"], ["fomc"])
    assert not is_relevant("Local bakery wins award", "", "media", ["ceo"], ["fomc"])
    assert is_relevant("Federal Reserve issues FOMC statement", "", "primary", ["ceo"], ["fomc"])
    assert not is_relevant("Board announces approval of application by X Bancorp", "", "primary", ["ceo"], ["fomc"])


def test_is_fresh():
    now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    assert is_fresh("2026-11-13T10:00:00+00:00", 3, now)
    assert not is_fresh("2026-11-01T10:00:00+00:00", 3, now)
    assert is_fresh(None, 3, now)


def test_refilter_clears_stale_backlog(conn, cfg):
    pipeline.ingest(conn, cfg, fetch=lambda feed, ua: parse_feed(RSS, feed))
    assert pipeline.prefilter(conn, cfg) == 1
    cfg.max_age_days = 0
    assert pipeline.prefilter(conn, cfg) == 0
    assert len(db.articles_by_status(conn, "filtered")) == 0


def test_parse_signals_validates():
    signals = scoring.parse_signals(LLM_REPLY)
    assert len(signals) == 1
    assert signals[0]["target"] == "NVDA" and signals[0]["magnitude"] == 5
    clamped = scoring.parse_signals(
        '{"signals":[{"level":"makro","target":"DAX","direction":"long","magnitude":9,"confidence":3}]}')
    assert clamped[0]["magnitude"] == 5 and clamped[0]["confidence"] == 1.0
    with pytest.raises(ValueError):
        scoring.parse_signals("kein json")


def test_full_run_pushes_once(conn, cfg):
    sent = []
    pipeline.ingest(conn, cfg, fetch=lambda feed, ua: parse_feed(RSS, feed))
    assert pipeline.prefilter(conn, cfg) == 1
    created = pipeline.score(conn, cfg, scorer=lambda art, key, model: scoring.parse_signals(LLM_REPLY))
    assert created == 1
    sender = lambda token, chat, text: sent.append(text)
    assert pipeline.push(conn, cfg, sender=sender) == 1
    assert pipeline.push(conn, cfg, sender=sender) == 0
    assert "SHORT NVDA" in sent[0] and "example.com/a" in sent[0]
    assert pipeline.digest(conn, cfg, "US-Schluss", sender=sender) == 1
    assert pipeline.digest(conn, cfg, sender=sender) == 0


def test_scoring_failure_does_not_stop_run(conn, cfg):
    pipeline.ingest(conn, cfg, fetch=lambda feed, ua: parse_feed(RSS, feed))
    pipeline.prefilter(conn, cfg)

    def boom(art, key, model):
        raise RuntimeError("API down")

    assert pipeline.score(conn, cfg, scorer=boom) == 0
    assert len(db.articles_by_status(conn, "failed")) == 1


def test_digest_splits_long_messages():
    sig = {"direction": "long", "target": "DAX", "region": "DE", "level": "makro", "magnitude": 3,
           "confidence": 0.6, "horizon": "woche", "rationale": "x" * 400, "invalidation": "",
           "related": "", "article_url": "https://example.com", "article_source": "S", "article_title": "T"}
    messages = telegram.format_digest([sig] * 20)
    assert len(messages) > 1 and all(len(m) <= telegram.MAX_LEN for m in messages)
