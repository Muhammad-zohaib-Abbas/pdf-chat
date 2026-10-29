"""PDF ingestion: extract, chunk, embed, and store for one website."""

import hashlib
from pathlib import Path
from uuid import UUID

from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from app import config
from app.database import get_connection
from app.documents import extract_pdf_pages, split_text_into_chunks
from app.embeddings import generate_embeddings


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _already_stored(cursor, site_id: UUID, file_hash: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM documents WHERE site_id = %s AND file_hash = %s LIMIT 1",
        (site_id, file_hash),
    )
    return cursor.fetchone() is not None


def ingest_pdf_file(
    pdf_path: str,
    site_id: UUID,
    display_name: str | None = None,
) -> dict:
    """Store a PDF for one site. Returns a summary dict.

    The same file (same bytes) uploaded twice by one site is stored once.
    Embeddings are created before the database transaction starts, so a
    failing API call never leaves a half-saved document or a long-open
    transaction.
    """
    path = Path(pdf_path)

    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    name = display_name or path.name
    file_hash = hash_file(path)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            if _already_stored(cursor, site_id, file_hash):
                return {
                    "document_id": file_hash,
                    "filename": name,
                    "duplicate": True,
                }

    pages = extract_pdf_pages(str(path), max_pages=config.MAX_PDF_PAGES)

    if not pages:
        raise ValueError(
            "No extractable text found. The PDF may be scanned "
            "or contain images instead of selectable text."
        )

    rows = []  # (page_number, page_text, [(chunk_index, chunk_text), ...])
    for page in pages:
        chunks = split_text_into_chunks(page["content"])
        rows.append((
            page["page_number"],
            page["content"],
            list(enumerate(chunks, start=1)),
        ))

    all_chunks = [text for _, _, chunks in rows for _, text in chunks]

    if len(all_chunks) > config.MAX_CHUNKS_PER_DOCUMENT:
        raise ValueError(
            "The document is too large to index "
            f"(more than {config.MAX_CHUNKS_PER_DOCUMENT} text chunks)."
        )

    embeddings = iter(generate_embeddings(all_chunks, "RETRIEVAL_DOCUMENT"))

    with get_connection() as connection:
        register_vector(connection)

        with connection.cursor() as cursor:
            # Serialise concurrent uploads of the same file by this site.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{site_id}:{file_hash}",),
            )

            if _already_stored(cursor, site_id, file_hash):
                return {
                    "document_id": file_hash,
                    "filename": name,
                    "duplicate": True,
                }

            for page_number, page_text, chunks in rows:
                cursor.execute(
                    """
                    INSERT INTO documents
                        (site_id, file_hash, document_name, page_number, content)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (site_id, file_hash, name, page_number, page_text),
                )
                document_row_id = cursor.fetchone()[0]

                cursor.executemany(
                    """
                    INSERT INTO document_chunks
                        (document_id, content, metadata, embedding)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            document_row_id,
                            text,
                            Jsonb({
                                "source": name,
                                "page_number": page_number,
                                "chunk_index": chunk_index,
                            }),
                            Vector(next(embeddings)),
                        )
                        for chunk_index, text in chunks
                    ],
                )

    return {
        "document_id": file_hash,
        "filename": name,
        "duplicate": False,
        "pages": len(pages),
        "chunks": len(all_chunks),
    }
