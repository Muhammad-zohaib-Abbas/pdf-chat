"""Small in-memory rate limiter (per website, per bucket).

It lives in the memory of one server process. That is correct for a single
`uvicorn` process; with several workers or servers each has its own counter
(use Redis or a reverse proxy limit when you deploy that way).
"""

import threading
import time
from collections import defaultdict, deque
from uuid import UUID

from fastapi import Depends, HTTPException

from app import config
from app.auth import get_current_site

_hits: dict[tuple[str, UUID], deque] = defaultdict(deque)
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _hits.clear()


def rate_limited(bucket: str, config_name: str):
    """Build a dependency: authenticates, then enforces the bucket's limit."""

    def dependency(site_id: UUID = Depends(get_current_site)) -> UUID:
        limit = getattr(config, config_name)
        now = time.monotonic()

        with _lock:
            hits = _hits[(bucket, site_id)]

            while hits and now - hits[0] >= 60:
                hits.popleft()

            if len(hits) >= limit:
                retry_after = max(1, int(60 - (now - hits[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down.",
                    headers={"Retry-After": str(retry_after)},
                )

            hits.append(now)

        return site_id

    return dependency
