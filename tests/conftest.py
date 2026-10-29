"""Test setup.

These tests wipe and recreate the schema of the database in TEST_DATABASE_URL,
so that database name MUST contain "test". Gemini is replaced by fakes, so no
API key or network is needed.
"""

import hashlib
import math
import os
import re
from urllib.parse import urlparse

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if not TEST_DATABASE_URL:
    pytest.skip("Set TEST_DATABASE_URL to run these tests.", allow_module_level=True)

if "test" not in urlparse(TEST_DATABASE_URL).path.lower():
    raise RuntimeError("TEST_DATABASE_URL database name must contain 'test'.")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["GEMINI_API_KEY"] = "test-key-not-real"

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
from app import ratelimit, sites  # noqa: E402
from scripts.migrate_db import migrate  # noqa: E402


def fake_vector(text: str) -> list[float]:
    """Bag-of-words vector: texts sharing words are close together."""
    vector = [0.0] * 768
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        index = int(hashlib.md5(word.encode()).hexdigest(), 16) % 768
        vector[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def fake_generate(prompt: str) -> str:
    if prompt.startswith("Rewrite"):
        match = re.search(r"Latest question:\n(.*?)\n\nStandalone", prompt, re.S)
        return match.group(1).strip()
    return "Here is the answer."


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr("app.ingestion.generate_embeddings",
                        lambda texts, task_type="RETRIEVAL_DOCUMENT": [fake_vector(t) for t in texts])
    monkeypatch.setattr("app.rag.generate_embedding",
                        lambda text, task_type="RETRIEVAL_QUERY": fake_vector(text))
    monkeypatch.setattr("app.rag._generate", fake_generate)


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("DROP SCHEMA IF EXISTS extensions CASCADE")
        connection.execute("CREATE SCHEMA public")
        connection.execute("CREATE SCHEMA extensions")
    migrate()


@pytest.fixture(autouse=True)
def clean(database):
    ratelimit.reset()
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute("TRUNCATE sites, documents, conversations CASCADE")


@pytest.fixture
def client():
    return TestClient(api.app)


@pytest.fixture
def site_a():
    site_id, key = sites.create_site("Site A")
    return {"id": site_id, "headers": {"X-API-Key": key}}


@pytest.fixture
def site_b():
    site_id, key = sites.create_site("Site B")
    return {"id": site_id, "headers": {"X-API-Key": key}}


def make_pdf(pages: list[list[str]]) -> bytes:
    """Build a small valid text PDF (one list of lines per page)."""
    objects = {}
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, lines in enumerate(pages):
        body = "BT /F1 12 Tf 14 TL 72 720 Td " + " T* ".join(
            "(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj"
            for line in lines
        ) + " ET"
        stream = body.encode()
        page_id, content_id = page_ids[i], page_ids[i] + 1
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode()
        objects[content_id] = (
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(output)
        output += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"
    xref = len(output)
    size = max(objects) + 1
    output += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for number in range(1, size):
        output += b"%010d 00000 n \n" % offsets[number]
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
    return bytes(output)


@pytest.fixture
def pdf_bytes():
    return make_pdf([
        ["Our refund policy allows returns within 30 days of purchase."],
        ["Shipping to Europe takes five business days."],
    ])
