import pytest

from newsbroker import db, scoring

SIG = {"level": "titel", "target": "NVDA", "region": "US", "direction": "short", "magnitude": 5,
       "horizon": "tage", "confidence": 0.8, "surprise": 5, "rationale": "x"}


def test_extract_from_tool_use():
    resp = {"stop_reason": "tool_use", "content": [
        {"type": "text", "text": "ok"},
        {"type": "tool_use", "name": "report_signals", "input": {"signals": [SIG, {"level": "x"}]}}]}
    out = scoring.extract_signals(resp)
    assert len(out) == 1 and out[0]["target"] == "NVDA" and out[0]["related"] == []


def test_extract_empty_tool_use():
    resp = {"content": [{"type": "tool_use", "name": "report_signals", "input": {"signals": []}}]}
    assert scoring.extract_signals(resp) == []


def test_extract_text_fallback_and_error():
    resp = {"content": [{"type": "text", "text": '{"signals": []}'}]}
    assert scoring.extract_signals(resp) == []
    with pytest.raises(ValueError, match="stop_reason=max_tokens"):
        scoring.extract_signals({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "nix"}]})


def test_score_article_request_shape(monkeypatch):
    seen = {}

    class Resp:
        ok = True

        def json(self):
            return {"content": [{"type": "tool_use", "name": "report_signals", "input": {"signals": [SIG]}}]}

    def fake_post(url, headers, json, timeout):
        seen.update(json)
        return Resp()

    monkeypatch.setattr(scoring.requests, "post", fake_post)
    art = {"source": "S", "source_kind": "media", "region": "US", "title": "T", "summary": ""}
    assert scoring.score_article(art, "k", "m")[0]["target"] == "NVDA"
    assert seen["tool_choice"] == {"type": "tool", "name": "report_signals"}
    assert seen["tools"][0]["input_schema"]["required"] == ["signals"]


def test_retry_failed():
    conn = db.connect(":memory:")
    db.insert_article(conn, source="s", source_kind="media", region="US", url="u", title="t",
                      summary="", published_at=None)
    db.set_status(conn, 1, "failed")
    assert db.retry_failed(conn) == 1
    assert len(db.articles_by_status(conn, "filtered")) == 1
