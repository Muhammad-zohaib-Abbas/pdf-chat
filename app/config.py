import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a whole number") from error


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing from .env")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing from .env")

# Optional: used only by the command-line scripts in scripts/.
DEFAULT_SITE_ID = os.getenv("DEFAULT_SITE_ID")

# Browsers only need CORS if a web page calls this API directly. A WordPress
# plugin calling from PHP (server to server) does not need it. Leave empty
# unless you know you need it. Example: https://example.com,https://shop.example.com
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# Upload limits.
MAX_UPLOAD_MB = _int_env("MAX_UPLOAD_MB", 20)
MAX_PDF_PAGES = _int_env("MAX_PDF_PAGES", 500)
MAX_CHUNKS_PER_DOCUMENT = _int_env("MAX_CHUNKS_PER_DOCUMENT", 3000)

# Requests per minute, per website (API key).
RATE_LIMIT_ASK_PER_MIN = _int_env("RATE_LIMIT_ASK_PER_MIN", 20)
RATE_LIMIT_UPLOAD_PER_MIN = _int_env("RATE_LIMIT_UPLOAD_PER_MIN", 5)
RATE_LIMIT_DEFAULT_PER_MIN = _int_env("RATE_LIMIT_DEFAULT_PER_MIN", 120)
