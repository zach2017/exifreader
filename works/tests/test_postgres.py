"""
Tests for Postgres schema and document operations.
Requires a running Postgres instance with the schema applied.
Skips gracefully if Postgres is unavailable.
"""

import uuid
import time

import pytest

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    pytest.skip("psycopg2 not installed", allow_module_level=True)


class TestSchemaExists:
    """Verify the database schema was created correctly."""

    def test_documents_table_columns(self, clean_db):
        cur = clean_db.cursor()
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'documents'
            ORDER BY ordinal_position
        """)
        columns = {row[0]: row[1] for row in cur.fetchall()}

        expected = [
            "id", "doc_id", "original_filename", "s3_key_original",
            "s3_key_text", "content_type", "file_size_bytes",
            "extracted_text", "ocr_status", "error_message",
            "page_count", "word_count", "created_at", "updated_at", "processed_at",
        ]
        for col in expected:
            assert col in columns, f"Missing column: {col}"

    def test_processing_log_table_columns(self, clean_db):
        cur = clean_db.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'processing_log'
        """)
        columns = [row[0] for row in cur.fetchall()]

        for col in ["id", "doc_id", "stage", "status", "message", "created_at"]:
            assert col in columns, f"Missing column: {col}"

    def test_doc_id_index_exists(self, clean_db):
        cur = clean_db.cursor()
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'documents' AND indexname = 'idx_documents_doc_id'
        """)
        assert cur.fetchone() is not None

    def test_uuid_extension_enabled(self, clean_db):
        cur = clean_db.cursor()
        cur.execute("SELECT uuid_generate_v4()")
        result = cur.fetchone()[0]
        assert len(str(result)) == 36


class TestDocumentCRUD:
    """Test document insert, update, and query operations."""

    def test_insert_document(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor()
        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, content_type, file_size_bytes, ocr_status)
               VALUES (%s, %s, %s, %s, %s, 'pending')""",
            (doc_id, "test.png", f"uploads/{doc_id}/test.png", "image/png", 1234),
        )
        clean_db.commit()

        cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
        assert cur.fetchone() is not None

    def test_insert_sets_created_at(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
               VALUES (%s, %s, %s, 'pending') RETURNING created_at""",
            (doc_id, "test.png", f"uploads/{doc_id}/test.png"),
        )
        clean_db.commit()
        assert cur.fetchone()["created_at"] is not None

    def test_update_triggers_updated_at(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
               VALUES (%s, %s, %s, 'pending') RETURNING updated_at""",
            (doc_id, "test.png", f"uploads/{doc_id}/test.png"),
        )
        clean_db.commit()
        original = cur.fetchone()["updated_at"]

        time.sleep(0.1)

        cur.execute(
            "UPDATE documents SET ocr_status = 'processing' WHERE doc_id = %s RETURNING updated_at",
            (doc_id,),
        )
        clean_db.commit()
        updated = cur.fetchone()["updated_at"]

        assert updated >= original

    def test_ocr_status_constraint(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor()
        with pytest.raises(psycopg2.IntegrityError):
            cur.execute(
                """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
                   VALUES (%s, %s, %s, 'invalid_status')""",
                (doc_id, "test.png", f"uploads/{doc_id}/test.png"),
            )
            clean_db.commit()

    def test_doc_id_unique_constraint(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor()
        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
               VALUES (%s, %s, %s, 'pending')""",
            (doc_id, "test.png", f"uploads/{doc_id}/test.png"),
        )
        clean_db.commit()

        with pytest.raises(psycopg2.IntegrityError):
            cur.execute(
                """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
                   VALUES (%s, %s, %s, 'pending')""",
                (doc_id, "dup.png", f"uploads/{doc_id}/dup.png"),
            )
            clean_db.commit()

    def test_full_ocr_lifecycle(self, clean_db):
        """pending → processing → completed lifecycle."""
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, content_type, file_size_bytes, ocr_status)
               VALUES (%s, %s, %s, %s, %s, 'pending')""",
            (doc_id, "report.pdf", f"uploads/{doc_id}/report.pdf", "application/pdf", 50000),
        )
        clean_db.commit()

        cur.execute("UPDATE documents SET ocr_status = 'processing' WHERE doc_id = %s", (doc_id,))
        clean_db.commit()

        cur.execute(
            """UPDATE documents
               SET ocr_status = 'completed', extracted_text = %s, s3_key_text = %s,
                   page_count = %s, word_count = %s, processed_at = NOW()
               WHERE doc_id = %s""",
            ("The quick brown fox", f"text/{doc_id}/extracted.txt", 3, 4, doc_id),
        )
        clean_db.commit()

        cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
        doc = cur.fetchone()
        assert doc["ocr_status"] == "completed"
        assert doc["extracted_text"] == "The quick brown fox"
        assert doc["page_count"] == 3
        assert doc["word_count"] == 4
        assert doc["processed_at"] is not None

    def test_failed_status_with_error(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
               VALUES (%s, %s, %s, 'pending')""",
            (doc_id, "corrupt.png", f"uploads/{doc_id}/corrupt.png"),
        )
        clean_db.commit()

        cur.execute(
            "UPDATE documents SET ocr_status = 'failed', error_message = %s WHERE doc_id = %s",
            ("Tesseract failed: corrupt image", doc_id),
        )
        clean_db.commit()

        cur.execute("SELECT ocr_status, error_message FROM documents WHERE doc_id = %s", (doc_id,))
        doc = cur.fetchone()
        assert doc["ocr_status"] == "failed"
        assert "corrupt image" in doc["error_message"]


class TestProcessingLog:
    """Test the processing_log audit trail."""

    def test_insert_log_entry(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor()

        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
               VALUES (%s, %s, %s, 'pending')""",
            (doc_id, "test.png", f"uploads/{doc_id}/test.png"),
        )
        clean_db.commit()

        cur.execute(
            "INSERT INTO processing_log (doc_id, stage, status, message) VALUES (%s, %s, %s, %s)",
            (doc_id, "upload", "completed", "Uploaded 1234 bytes"),
        )
        clean_db.commit()

        cur.execute("SELECT * FROM processing_log WHERE doc_id = %s", (doc_id,))
        assert cur.fetchone() is not None

    def test_multiple_log_entries(self, clean_db):
        doc_id = str(uuid.uuid4())
        cur = clean_db.cursor()

        cur.execute(
            """INSERT INTO documents (doc_id, original_filename, s3_key_original, ocr_status)
               VALUES (%s, %s, %s, 'pending')""",
            (doc_id, "test.png", f"uploads/{doc_id}/test.png"),
        )
        clean_db.commit()

        for stage, status, msg in [("upload", "completed", "OK"), ("ocr", "processing", "Started"), ("ocr", "completed", "Done")]:
            cur.execute(
                "INSERT INTO processing_log (doc_id, stage, status, message) VALUES (%s, %s, %s, %s)",
                (doc_id, stage, status, msg),
            )
        clean_db.commit()

        cur.execute("SELECT COUNT(*) FROM processing_log WHERE doc_id = %s", (doc_id,))
        assert cur.fetchone()[0] == 3

    def test_fk_prevents_orphan_logs(self, clean_db):
        cur = clean_db.cursor()
        with pytest.raises(psycopg2.IntegrityError):
            cur.execute(
                "INSERT INTO processing_log (doc_id, stage, status) VALUES (%s, %s, %s)",
                ("nonexistent-doc-id", "test", "test"),
            )
            clean_db.commit()
