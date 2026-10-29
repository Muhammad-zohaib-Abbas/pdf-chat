"""Database operations for websites (tenants). Used by scripts/manage_sites.py."""

from uuid import UUID

from app.auth import generate_api_key, hash_api_key
from app.database import get_connection


def create_site(name: str) -> tuple[UUID, str]:
    api_key = generate_api_key()

    with get_connection() as connection:
        site_id = connection.execute(
            "INSERT INTO sites (name, api_key_hash) VALUES (%s, %s) RETURNING id",
            (name, hash_api_key(api_key)),
        ).fetchone()[0]

    return site_id, api_key


def rotate_key(site_id: UUID) -> str | None:
    api_key = generate_api_key()

    with get_connection() as connection:
        row = connection.execute(
            "UPDATE sites SET api_key_hash = %s WHERE id = %s RETURNING id",
            (hash_api_key(api_key), site_id),
        ).fetchone()

    return api_key if row else None


def set_active(site_id: UUID, active: bool) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "UPDATE sites SET is_active = %s WHERE id = %s RETURNING id",
            (active, site_id),
        ).fetchone()

    return row is not None


def list_sites() -> list[tuple]:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, name, is_active, created_at FROM sites ORDER BY created_at"
        ).fetchall()


def adopt_legacy_data(site_id: UUID) -> tuple[int, int]:
    """Assign rows created before multi-site support to one site."""
    with get_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM sites WHERE id = %s", (site_id,)
        ).fetchone() is None:
            raise ValueError("Site not found.")

        documents = connection.execute(
            """
            UPDATE documents
            SET site_id = %s,
                file_hash = COALESCE(
                    file_hash,
                    encode(sha256(convert_to(document_name, 'UTF8')), 'hex')
                )
            WHERE site_id IS NULL
            """,
            (site_id,),
        ).rowcount
        conversations = connection.execute(
            "UPDATE conversations SET site_id = %s WHERE site_id IS NULL",
            (site_id,),
        ).rowcount

    return documents, conversations
