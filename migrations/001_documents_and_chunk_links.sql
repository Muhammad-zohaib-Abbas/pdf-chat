CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    document_name TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    content TEXT NOT NULL
);

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS document_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'document_chunks_document_id_fkey'
          AND conrelid = 'document_chunks'::regclass
    ) THEN
        ALTER TABLE document_chunks
            ADD CONSTRAINT document_chunks_document_id_fkey
            FOREIGN KEY (document_id) REFERENCES documents(id)
            ON DELETE CASCADE;
    END IF;
END
$$;

DO $$
DECLARE
    chunk RECORD;
    new_document_id BIGINT;
    source_name TEXT;
    source_page INTEGER;
BEGIN
    FOR chunk IN
        SELECT id, content, metadata
        FROM document_chunks
        WHERE document_id IS NULL
    LOOP
        source_name := COALESCE(
            NULLIF(chunk.metadata ->> 'source', ''),
            format('legacy_chunk_%s', chunk.id)
        );
        source_page := CASE
            WHEN COALESCE(chunk.metadata ->> 'page_number', '') ~ '^[0-9]+$'
                THEN (chunk.metadata ->> 'page_number')::INTEGER
            ELSE 1
        END;

        INSERT INTO documents (document_name, page_number, content)
        VALUES (source_name, GREATEST(source_page, 1), chunk.content)
        RETURNING id INTO new_document_id;

        UPDATE document_chunks
        SET document_id = new_document_id
        WHERE id = chunk.id;
    END LOOP;
END
$$;

CREATE INDEX IF NOT EXISTS document_chunks_document_id_idx
    ON document_chunks(document_id);
