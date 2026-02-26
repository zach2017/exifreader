-- ============================================================
-- OCR Document Storage Schema
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Documents table: stores metadata and extracted text
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_id          VARCHAR(255) UNIQUE NOT NULL,
    original_filename VARCHAR(512) NOT NULL,
    s3_key_original VARCHAR(1024) NOT NULL,
    s3_key_text     VARCHAR(1024),
    content_type    VARCHAR(128),
    file_size_bytes BIGINT,
    extracted_text  TEXT,
    ocr_status      VARCHAR(32) NOT NULL DEFAULT 'pending'
                        CHECK (ocr_status IN ('pending','processing','completed','failed')),
    error_message   TEXT,
    page_count      INTEGER,
    word_count      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

-- Index for fast lookup by doc_id
CREATE INDEX idx_documents_doc_id ON documents(doc_id);
CREATE INDEX idx_documents_ocr_status ON documents(ocr_status);
CREATE INDEX idx_documents_created_at ON documents(created_at DESC);

-- Processing log table for audit trail
CREATE TABLE processing_log (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      VARCHAR(255) NOT NULL REFERENCES documents(doc_id),
    stage       VARCHAR(64) NOT NULL,
    status      VARCHAR(32) NOT NULL,
    message     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_processing_log_doc_id ON processing_log(doc_id);

-- Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_documents_updated
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
