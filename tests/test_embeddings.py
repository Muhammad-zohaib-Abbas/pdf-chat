import pytest
import requests

from app import embeddings


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._payload


def no_sleep(monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda seconds: None)


def test_retries_on_429_then_succeeds(monkeypatch):
    no_sleep(monkeypatch)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            return FakeResponse(429)
        return FakeResponse(200, {"embedding": {"values": [0.1] * 768}})

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    assert len(embeddings.generate_embedding("hello")) == 768
    assert len(calls) == 3


def test_does_not_retry_client_errors(monkeypatch):
    no_sleep(monkeypatch)
    calls = []
    monkeypatch.setattr(embeddings.requests, "post",
                        lambda url, **kw: calls.append(url) or FakeResponse(400))
    with pytest.raises(requests.HTTPError):
        embeddings.generate_embedding("hello")
    assert len(calls) == 1


def test_batches_of_fifty(monkeypatch):
    sizes = []

    def fake_post(url, json=None, **kwargs):
        sizes.append(len(json["requests"]))
        return FakeResponse(200, {"embeddings": [{"values": [0.0] * 768}] * len(json["requests"])})

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    assert len(embeddings.generate_embeddings(["x"] * 120)) == 120
    assert sizes == [50, 50, 20]


def test_wrong_dimensions_rejected(monkeypatch):
    monkeypatch.setattr(embeddings.requests, "post",
                        lambda url, **kw: FakeResponse(200, {"embedding": {"values": [0.1] * 10}}))
    with pytest.raises(ValueError):
        embeddings.generate_embedding("hello")
