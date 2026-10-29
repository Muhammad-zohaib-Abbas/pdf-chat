-- Websites (tenants) and their hashed API keys.
CREATE TABLE IF NOT EXISTS sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    api_key_hash CHAR(64) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ownership + duplicate detection. Columns are nullable so existing rows
-- survive; run `python -m scripts.manage_sites adopt-legacy <site_id>`
-- to assign existing data to a site.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS file_hash CHAR(64),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS site_id UUID REFERENCES sites(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS documents_site_hash_idx
    ON documents (site_id, file_hash);

CREATE INDEX IF NOT EXISTS conversations_site_updated_idx
    ON conversations (site_id, updated_at DESC);
