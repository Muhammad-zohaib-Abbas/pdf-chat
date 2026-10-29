import psycopg
import pytest

from app import config
from scripts.migrate_db import migrate
from tests.conftest import TEST_DATABASE_URL, make_pdf


def upload(client, headers, data, name="policy.pdf"):
    return client.post(
        "/documents/upload",
        headers=headers,
        files={"file": (name, data, "application/pdf")},
    )


def count(sql):
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        return connection.execute(sql).fetchone()[0]


# ---------- migrations ----------

def test_migrations_can_run_twice():
    migrate()
    migrate()
    assert count("SELECT COUNT(*) FROM schema_migrations") == 4


# ---------- authentication ----------

@pytest.mark.parametrize("method,path", [
    ("get", "/me"), ("get", "/documents"), ("get", "/conversations"),
    ("post", "/ask"), ("post", "/conversations"),
    ("delete", "/documents/" + "a" * 64),
])
def test_endpoints_require_key(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    bad = {"X-API-Key": "kb_wrong"}
    assert getattr(client, method)(path, headers=bad).status_code == 401


def test_valid_key_and_disabled_site(client, site_a):
    assert client.get("/me", headers=site_a["headers"]).json()["name"] == "Site A"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute("UPDATE sites SET is_active = FALSE")
    assert client.get("/me", headers=site_a["headers"]).status_code == 401


def test_keys_are_stored_hashed(site_a):
    key = site_a["headers"]["X-API-Key"]
    assert count(f"SELECT COUNT(*) FROM sites WHERE api_key_hash = '{key}'") == 0


def test_public_endpoints(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


# ---------- uploads ----------

def test_upload_validation(client, site_a):
    h = site_a["headers"]
    assert upload(client, h, b"hello", "notes.txt").status_code == 400
    assert upload(client, h, b"not really a pdf", "fake.pdf").status_code == 400
    assert upload(client, h, b"", "empty.pdf").status_code == 400
    assert upload(client, h, b"%PDF-1.4 garbage", "broken.pdf").status_code == 400


def test_upload_too_large(client, site_a, monkeypatch, pdf_bytes):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0)
    assert upload(client, site_a["headers"], pdf_bytes).status_code == 413


def test_upload_list_and_duplicate(client, site_a, pdf_bytes):
    h = site_a["headers"]
    first = upload(client, h, pdf_bytes)
    assert first.status_code == 200, first.text
    assert first.json()["duplicate"] is False

    second = upload(client, h, pdf_bytes, "renamed.pdf")
    assert second.json()["duplicate"] is True
    assert count("SELECT COUNT(*) FROM documents") == 2  # 2 pages, stored once

    listing = client.get("/documents", headers=h).json()
    assert len(listing) == 1
    assert listing[0]["filename"] == "policy.pdf"
    assert (listing[0]["pages"], listing[0]["chunks"]) == (2, 2)


def test_scanned_pdf_without_text(client, site_a):
    response = upload(client, site_a["headers"], make_pdf([[""]]))
    assert response.status_code == 400
    assert "extractable text" in response.json()["detail"]


def test_embedding_failure_leaves_nothing_behind(client, site_a, pdf_bytes, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("embedding service down")
    monkeypatch.setattr("app.ingestion.generate_embeddings", boom)
    assert upload(client, site_a["headers"], pdf_bytes).status_code == 500
    assert count("SELECT COUNT(*) FROM documents") == 0


def test_delete_document_removes_chunks(client, site_a, pdf_bytes):
    h = site_a["headers"]
    document_id = upload(client, h, pdf_bytes).json()["document_id"]
    assert client.delete(f"/documents/{document_id}", headers=h).status_code == 200
    assert count("SELECT COUNT(*) FROM document_chunks") == 0
    assert client.delete(f"/documents/{document_id}", headers=h).status_code == 404
    assert client.delete("/documents/not-a-hash", headers=h).status_code == 404


# ---------- asking ----------

def test_ask_with_citation_and_follow_up(client, site_a, pdf_bytes):
    h = site_a["headers"]
    upload(client, h, pdf_bytes)

    first = client.post("/ask", headers=h, json={"question": "refund policy returns within 30 days"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["citations"] == [{"source": "policy.pdf", "page": 1}]

    follow_up = client.post("/ask", headers=h, json={
        "question": "Shipping Europe takes five business days",
        "conversation_id": body["conversation_id"],
    })
    assert follow_up.status_code == 200
    assert follow_up.json()["citations"] == [{"source": "policy.pdf", "page": 2}]

    messages = client.get(f"/conversations/{body['conversation_id']}/messages", headers=h).json()
    assert [m["role"] for m in messages] == ["user", "assistant"] * 2
    assert messages[1]["citations"] == [{"source": "policy.pdf", "page": 1}]


def test_ask_without_documents(client, site_a):
    response = client.post("/ask", headers=site_a["headers"], json={"question": "anything?"})
    assert response.status_code == 200
    assert response.json()["citations"] == []


def test_ask_validation(client, site_a):
    h = site_a["headers"]
    assert client.post("/ask", headers=h, json={"question": "   "}).status_code == 422
    assert client.post("/ask", headers=h, json={"question": "x" * 4001}).status_code == 422


def test_failed_ask_creates_no_conversation(client, site_a, monkeypatch):
    monkeypatch.setattr("app.rag._generate", lambda prompt: (_ for _ in ()).throw(RuntimeError("x")))
    upload_ok = upload(client, site_a["headers"], make_pdf([["alpha beta gamma"]]))
    assert upload_ok.status_code == 200
    response = client.post("/ask", headers=site_a["headers"], json={"question": "alpha beta gamma"})
    assert response.status_code == 500
    assert count("SELECT COUNT(*) FROM conversations") == 0


# ---------- isolation between websites ----------

def test_sites_are_isolated(client, site_a, site_b, pdf_bytes):
    a, b = site_a["headers"], site_b["headers"]
    document_id = upload(client, a, pdf_bytes).json()["document_id"]
    conversation = client.post("/ask", headers=a, json={"question": "refund policy returns"}).json()

    # B sees nothing of A's documents...
    assert client.get("/documents", headers=b).json() == []
    answer = client.post("/ask", headers=b, json={"question": "refund policy returns"}).json()
    assert answer["citations"] == []
    # ...cannot delete them...
    assert client.delete(f"/documents/{document_id}", headers=b).status_code == 404
    # ...and cannot read, continue or delete A's conversation.
    cid = conversation["conversation_id"]
    assert client.get(f"/conversations/{cid}/messages", headers=b).status_code == 404
    assert client.post("/ask", headers=b, json={"question": "hi", "conversation_id": cid}).status_code == 404
    assert client.delete(f"/conversations/{cid}", headers=b).status_code == 404
    assert cid not in [c["id"] for c in client.get("/conversations", headers=b).json()]

    # A is unaffected, and the same file can be uploaded by B independently.
    assert len(client.get("/documents", headers=a).json()) == 1
    assert upload(client, b, pdf_bytes).json()["duplicate"] is False


# ---------- conversations ----------

def test_conversation_crud(client, site_a):
    h = site_a["headers"]
    created = client.post("/conversations", headers=h, json={"title": "Hello"})
    assert created.status_code == 201
    cid = created.json()["id"]
    assert [c["id"] for c in client.get("/conversations", headers=h).json()] == [cid]
    assert client.get(f"/conversations/{cid}/messages", headers=h).json() == []
    assert client.delete(f"/conversations/{cid}", headers=h).status_code == 200
    assert client.get(f"/conversations/{cid}/messages", headers=h).status_code == 404


# ---------- rate limiting ----------

def test_rate_limit(client, site_a, site_b, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ASK_PER_MIN", 2)
    h = site_a["headers"]
    for _ in range(2):
        assert client.post("/ask", headers=h, json={"question": "hi"}).status_code == 200
    limited = client.post("/ask", headers=h, json={"question": "hi"})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    # Another website has its own allowance.
    assert client.post("/ask", headers=site_b["headers"], json={"question": "hi"}).status_code == 200
