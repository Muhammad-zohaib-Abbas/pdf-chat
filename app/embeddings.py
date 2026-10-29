import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import GEMINI_API_KEY

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
BATCH_SIZE = 50

_BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/{EMBEDDING_MODEL}"
)
EMBEDDING_URL = f"{_BASE_URL}:embedContent"
BATCH_EMBEDDING_URL = f"{_BASE_URL}:batchEmbedContents"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return error.response.status_code in RETRYABLE_STATUS
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, max=20),
    reraise=True,
)
def _post(url: str, payload: dict) -> dict:
    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _request_body(text: str, task_type: str) -> dict:
    return {
        "model": f"models/{EMBEDDING_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        "outputDimensionality": EMBEDDING_DIMENSIONS,
    }


def _check_dimensions(values: list[float]) -> list[float]:
    if len(values) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Expected {EMBEDDING_DIMENSIONS} dimensions, got {len(values)}"
        )
    return values


def generate_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float]:
    if not text.strip():
        raise ValueError("Text cannot be empty")

    data = _post(EMBEDDING_URL, _request_body(text, task_type))
    return _check_dimensions(data["embedding"]["values"])


def generate_embeddings(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Embed many texts with few requests (up to 50 per request)."""
    if any(not text.strip() for text in texts):
        raise ValueError("Text cannot be empty")

    embeddings: list[list[float]] = []

    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        data = _post(
            BATCH_EMBEDDING_URL,
            {"requests": [_request_body(text, task_type) for text in batch]},
        )
        returned = data["embeddings"]

        if len(returned) != len(batch):
            raise ValueError("Embedding service returned the wrong item count")

        embeddings.extend(_check_dimensions(item["values"]) for item in returned)

    return embeddings
