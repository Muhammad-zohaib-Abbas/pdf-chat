# Update notes

## Apply (PowerShell, from D:\python\fastapi-ai-ask-api-v2, venv active)

    pip install -r requirements.txt
    python -m scripts.migrate_db
    python -m scripts.manage_sites create --name "My First Site" --adopt-legacy
    # copy the printed API key somewhere safe: it is shown once
    uvicorn api:app --reload

`--adopt-legacy` assigns your existing documents and conversations to that site.
Omit it on a fresh database. Back up the database first if it matters.

## Test

    python -m scripts.smoke_test --pdf "C:\path\to\file.pdf" --question "..." --api-key kb_xxx

Automated tests (need a THROWAWAY database whose name contains "test"; they wipe it):

    pip install -r requirements-dev.txt
    $env:TEST_DATABASE_URL = "postgresql://user:pass@localhost:5432/kb_test"
    python -m pytest

## Endpoints (all but / and /health need header X-API-Key)

| Method | Path | Purpose |
|---|---|---|
| GET | /health | DB check |
| GET | /me | test the key |
| POST | /documents/upload | upload PDF (multipart field `file`) |
| GET | /documents | list this site's documents |
| DELETE | /documents/{document_id} | delete a document and its chunks |
| POST | /ask | `{question, conversation_id?}` |
| POST/GET | /conversations | create / list |
| GET | /conversations/{id}/messages | history |
| DELETE | /conversations/{id} | delete |
