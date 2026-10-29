"""API-key authentication. Each website has its own key.

Only a SHA-256 hash of the key is stored, so a database leak does not reveal
working keys. Keys are long random strings, so a fast hash is appropriate
(unlike human passwords).
"""

import hashlib
import secrets
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from app.database import get_connection

KEY_PREFIX = "kb_"


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def get_current_site(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> UUID:
    """FastAPI dependency: returns the site id for a valid key, else 401."""
    unauthorized = HTTPException(
        status_code=401,
        detail="Invalid or missing API key.",
    )

    if not x_api_key or len(x_api_key) > 200:
        raise unauthorized

    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM sites WHERE api_key_hash = %s AND is_active",
            (hash_api_key(x_api_key),),
        ).fetchone()

    if row is None:
        raise unauthorized

    return row[0]


def get_site_row(site_id: UUID = Depends(get_current_site)) -> tuple:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, name FROM sites WHERE id = %s", (site_id,)
        ).fetchone()
