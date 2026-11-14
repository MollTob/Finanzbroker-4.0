import pytest

from newsbroker import telegram


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.ok = status, payload, status < 400

    def json(self):
        return self._payload


def test_401_message_hides_token(monkeypatch):
    monkeypatch.setattr(telegram.requests, "request",
                        lambda *a, **k: FakeResp(401, {"ok": False, "description": "Unauthorized"}))
    with pytest.raises(telegram.TelegramError) as err:
        telegram.find_chat_ids("123:SECRET")
    assert "SECRET" not in str(err.value) and "401" in str(err.value)


def test_network_error_hides_token(monkeypatch):
    def boom(method, url, **k):
        raise telegram.requests.ConnectionError(f"failed for {url}")
    monkeypatch.setattr(telegram.requests, "request", boom)
    with pytest.raises(telegram.TelegramError) as err:
        telegram.send("123:SECRET", "1", "hi")
    assert "SECRET" not in str(err.value)
    assert err.value.__cause__ is None


def test_find_chat_ids(monkeypatch):
    payload = {"ok": True, "result": [{"message": {"chat": {"id": 42, "first_name": "Tobi"}}}, {"edited": {}}]}
    monkeypatch.setattr(telegram.requests, "request", lambda *a, **k: FakeResp(200, payload))
    assert telegram.find_chat_ids("t") == [(42, "Tobi")]
