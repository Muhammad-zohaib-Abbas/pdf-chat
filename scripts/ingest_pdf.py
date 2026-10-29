r"""Ingest a PDF from the command line.

    python -m scripts.ingest_pdf "path\to\file.pdf" --site <site_id>

--site can be omitted if DEFAULT_SITE_ID is set in .env.
"""

import argparse
import sys
from uuid import UUID

from app.config import DEFAULT_SITE_ID
from app.ingestion import ingest_pdf_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument("--site", default=DEFAULT_SITE_ID)
    args = parser.parse_args()

    if not args.site:
        print("Provide --site <site_id> or set DEFAULT_SITE_ID in .env.")
        return 1

    try:
        result = ingest_pdf_file(args.pdf_path, UUID(args.site))
    except Exception as error:
        print(f"PDF ingestion failed: {error}")
        return 1

    if result["duplicate"]:
        print(f"{result['filename']} was already uploaded; nothing changed.")
    else:
        print(
            f"Stored {result['filename']}: {result['pages']} pages, "
            f"{result['chunks']} chunks."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
