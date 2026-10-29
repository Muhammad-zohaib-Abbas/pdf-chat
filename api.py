import json
import logging
import re
import tempfile
from pathlib import Path
from uuid import UUID

import requests
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import config
from app.auth import get_site_row
from app.database import get_connection
from app.ingestion import ingest_pdf_file
from app.ratelimit import rate_limited
from app.rag import answer_question_with_sources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PDF Knowledge Assistant")

if config.ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

# Every endpoint except "/" and "/health" needs a valid X-API-Key header.
# The dependency returns the id of the website that owns the key, and every
# query below filters by that id, so one site can never see another's data.
default_site = rate_limited("default", "RATE_LIMIT_DEFAULT_PER_MIN")
ask_site = rate_limited("ask", "RATE_LIMIT_ASK_PER_MIN")
upload_site = rate_limited("upload", "RATE_LIMIT_UPLOAD_PER_MIN")


# ---------- schemas ----------

class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class Citation(BaseModel):
    source: str
    page: int


class AskResponse(BaseModel):
    answer: str
    success: bool
    citations: list[Citation]
    conversation_id: UUID


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=255)


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    created_at: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    citations: list[Citation]
    created_at: str


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    pages: int
    chunks: int
    uploaded_at: str


# ---------- helpers ----------

def _is_busy_error(error: Exception) -> bool:
    """True if Gemini (generation or embeddings) is overloaded or rate-limiting."""
    if getattr(error, "code", None) in (429, 503):
        return True
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return error.response.status_code in (429, 503)
    return isinstance(error, (requests.ConnectionError, requests.Timeout))


def _clean_filename(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:200]


def _conversation_exists(cursor, conversation_id: UUID, site_id: UUID) -> bool:
    cursor.execute(
        "SELECT 1 FROM conversations WHERE id = %s AND site_id = %s",
        (conversation_id, site_id),
    )
    return cursor.fetchone() is not None


# ---------- public ----------

@app.get("/")
def home():
    return {"name": "PDF Knowledge Assistant", "status": "ready"}


@app.get("/health")
def health():
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1")
    except Exception:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable.")
    return {"status": "ok"}


# ---------- authenticated ----------

@app.get("/me")
def me(site: tuple = Depends(get_site_row)):
    """Lets a client (e.g. the WordPress plugin) test its API key."""
    return {"site_id": site[0], "name": site[1]}


@app.post("/ask", response_model=AskResponse)
def ask(data: AskRequest, site_id: UUID = Depends(ask_site)):
    question = data.question.strip()

    if not question:
        raise HTTPException(status_code=422, detail="Question must not be blank.")

    try:
        history = []

        if data.conversation_id is not None:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    if not _conversation_exists(cursor, data.conversation_id, site_id):
                        raise HTTPException(
                            status_code=404,
                            detail="Conversation not found.",
                        )

                    # Most recent 10 messages, oldest first.
                    cursor.execute(
                        """
                        SELECT role, content
                        FROM messages
                        WHERE conversation_id = %s
                        ORDER BY created_at DESC, id DESC
                        LIMIT 10
                        """,
                        (data.conversation_id,),
                    )
                    history = [
                        {"role": role, "content": content}
                        for role, content in reversed(cursor.fetchall())
                    ]

        result = answer_question_with_sources(question, site_id, history)

        # Save only after a successful answer, so failures leave no
        # empty conversations behind.
        with get_connection() as connection:
            with connection.cursor() as cursor:
                conversation_id = data.conversation_id

                if conversation_id is None:
                    cursor.execute(
                        """
                        INSERT INTO conversations (site_id, title)
                        VALUES (%s, %s)
                        RETURNING id
                        """,
                        (site_id, question[:80]),
                    )
                    conversation_id = cursor.fetchone()[0]

                cursor.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, citations)
                    VALUES (%s, 'user', %s, '[]'::jsonb)
                    """,
                    (conversation_id, question),
                )
                cursor.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, citations)
                    VALUES (%s, 'assistant', %s, %s::jsonb)
                    """,
                    (
                        conversation_id,
                        result["answer"],
                        json.dumps(result["citations"]),
                    ),
                )
                cursor.execute(
                    "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
                    (conversation_id,),
                )

        return {
            **result,
            "success": True,
            "conversation_id": conversation_id,
        }

    except HTTPException:
        raise
    except Exception as error:
        if _is_busy_error(error):
            logger.warning("AI service temporarily unavailable: %s", error)
            raise HTTPException(
                status_code=503,
                detail="The AI service is temporarily busy. Please retry shortly.",
                headers={"Retry-After": "5"},
            ) from error

        logger.exception("Failed to answer question")
        raise HTTPException(
            status_code=500,
            detail="Unable to answer the question right now.",
        ) from error


# ---------- documents ----------

@app.post("/documents/upload")
def upload_pdf(
    file: UploadFile = File(...),
    site_id: UUID = Depends(upload_site),
):
    filename = _clean_filename(file.filename)

    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    max_size = config.MAX_UPLOAD_MB * 1024 * 1024

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Our own file name on disk; the client's name is only a label.
            pdf_path = Path(temp_dir) / "upload.pdf"
            total_size = 0
            

            with pdf_path.open("wb") as destination:
                while True:
                    chunk = file.file.read(1024 * 1024)

                    if not chunk:
                        break

                    if total_size == 0 and not chunk.startswith(b"%PDF-"):
                        raise HTTPException(
                            status_code=400,
                            detail="The file is not a valid PDF.",
                        )

                    total_size += len(chunk)

                    if total_size > max_size:
                        raise HTTPException(
                            status_code=413,
                            detail=f"PDF must not exceed {config.MAX_UPLOAD_MB} MB.",
                        )

                    destination.write(chunk)

            if total_size == 0:
                raise HTTPException(
                    status_code=400,
                    detail="The uploaded file is empty.",
                )

            result = ingest_pdf_file(str(pdf_path), site_id, display_name=filename)

        return {
            "success": True,
            **result,
            "message": (
                "This PDF was already uploaded. Nothing was changed."
                if result["duplicate"]
                else "PDF processed and saved successfully."
            ),
        }

    except HTTPException:
        raise
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        if _is_busy_error(error):
            raise HTTPException(
                status_code=503,
                detail="The AI service is temporarily busy. Please retry shortly.",
                headers={"Retry-After": "10"},
            ) from error

        logger.exception("PDF ingestion failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to process the PDF right now.",
        ) from error
    finally:
        file.file.close()


@app.get("/documents", response_model=list[DocumentResponse])
def list_documents(site_id: UUID = Depends(default_site)):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                d.file_hash,
                MIN(d.document_name),
                COUNT(DISTINCT d.id),
                COUNT(dc.id),
                MIN(d.created_at)
            FROM documents d
            LEFT JOIN document_chunks dc ON dc.document_id = d.id
            WHERE d.site_id = %s AND d.file_hash IS NOT NULL
            GROUP BY d.file_hash
            ORDER BY MIN(d.created_at) DESC
            """,
            (site_id,),
        ).fetchall()

    return [
        {
            "document_id": file_hash,
            "filename": name,
            "pages": pages,
            "chunks": chunks,
            "uploaded_at": uploaded.isoformat(),
        }
        for file_hash, name, pages, chunks, uploaded in rows
    ]


@app.delete("/documents/{document_id}")
def delete_document(document_id: str, site_id: UUID = Depends(default_site)):
    if not re.fullmatch(r"[0-9a-f]{64}", document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    with get_connection() as connection:
        # Chunks are removed automatically (ON DELETE CASCADE).
        deleted = connection.execute(
            "DELETE FROM documents WHERE site_id = %s AND file_hash = %s",
            (site_id, document_id),
        ).rowcount

    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document not found.")

    return {"success": True}


# ---------- conversations ----------

@app.post("/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(
    data: ConversationCreate,
    site_id: UUID = Depends(default_site),
):
    title = data.title.strip()

    if not title:
        raise HTTPException(
            status_code=422,
            detail="Conversation title must not be blank.",
        )

    with get_connection() as connection:
        conversation = connection.execute(
            """
            INSERT INTO conversations (site_id, title)
            VALUES (%s, %s)
            RETURNING id, title, created_at
            """,
            (site_id, title),
        ).fetchone()

    return {
        "id": conversation[0],
        "title": conversation[1],
        "created_at": conversation[2].isoformat(),
    }


@app.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    site_id: UUID = Depends(default_site),
):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, title, created_at
            FROM conversations
            WHERE site_id = %s
            ORDER BY updated_at DESC, id
            LIMIT %s OFFSET %s
            """,
            (site_id, limit, offset),
        ).fetchall()

    return [
        {"id": row[0], "title": row[1], "created_at": row[2].isoformat()}
        for row in rows
    ]


@app.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
def list_messages(
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    site_id: UUID = Depends(default_site),
):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            if not _conversation_exists(cursor, conversation_id, site_id):
                raise HTTPException(status_code=404, detail="Conversation not found.")

            cursor.execute(
                """
                SELECT id, role, content, citations, created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY created_at, id
                LIMIT %s OFFSET %s
                """,
                (conversation_id, limit, offset),
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "citations": row[3],
            "created_at": row[4].isoformat(),
        }
        for row in rows
    ]


@app.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: UUID,
    site_id: UUID = Depends(default_site),
):
    with get_connection() as connection:
        deleted = connection.execute(
            "DELETE FROM conversations WHERE id = %s AND site_id = %s",
            (conversation_id, site_id),
        ).rowcount

    if deleted == 0:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return {"success": True}
