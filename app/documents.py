from pypdf import PdfReader
from pypdf.errors import PyPdfError


def extract_pdf_pages(pdf_path: str, max_pages: int | None = None) -> list[dict]:
    """Extract text from a PDF while preserving page numbers."""
    try:
        reader = PdfReader(pdf_path)

        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("The PDF is password protected.")

        if max_pages is not None and len(reader.pages) > max_pages:
            raise ValueError(f"The PDF has more than {max_pages} pages.")

        pages = []

        for page_number, page in enumerate(reader.pages, start=1):
            # PostgreSQL text columns cannot store NUL characters.
            text = (page.extract_text() or "").replace("\x00", "").strip()

            if text:
                pages.append({
                    "page_number": page_number,
                    "content": text,
                })

        return pages
    except PyPdfError as error:
        raise ValueError("The file could not be read as a PDF.") from error


def split_text_into_chunks(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[str]:
    """Split text into overlapping character-based chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size")

    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end == len(text):
            break

        start = end - overlap

    return chunks
