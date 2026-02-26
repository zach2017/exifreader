"""
Tests: FastAPI API endpoints.
Requires Postgres to be running. Uses moto for S3.
Skips gracefully if Postgres is unavailable.
"""

import io
import os
import sys
import uuid

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api-server"))


class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_returns_200(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "checks" in data

    def test_health_includes_tesseract(self, api_client):
        data = api_client.get("/health").json()
        assert "tesseract" in data["checks"]

    def test_health_includes_postgres(self, api_client):
        data = api_client.get("/health").json()
        assert "postgres" in data["checks"]


class TestUploadEndpoint:
    """Test POST /upload endpoint."""

    def test_upload_image(self, api_client, sample_image_bytes):
        resp = api_client.post(
            "/upload",
            files={"file": ("test.png", io.BytesIO(sample_image_bytes), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "doc_id" in data
        assert data["message"] == "Document uploaded successfully"
        assert len(data["doc_id"]) == 36  # UUID

    def test_upload_creates_db_record(self, api_client, db_conn, sample_image_bytes):
        resp = api_client.post(
            "/upload",
            files={"file": ("record_test.png", io.BytesIO(sample_image_bytes), "image/png")},
        )
        doc_id = resp.json()["doc_id"]

        with db_conn.cursor() as cur:
            cur.execute("SELECT doc_id, original_filename, ocr_status FROM documents WHERE doc_id = %s", (doc_id,))
            row = cur.fetchone()

        assert row is not None
        assert row[0] == doc_id
        assert row[1] == "record_test.png"
        assert row[2] == "pending"

    def test_upload_stores_to_s3(self, api_client, s3_mock, sample_image_bytes):
        resp = api_client.post(
            "/upload",
            files={"file": ("s3_test.png", io.BytesIO(sample_image_bytes), "image/png")},
        )
        doc_id = resp.json()["doc_id"]

        s3_key = f"uploads/{doc_id}/s3_test.png"
        obj = s3_mock.get_object(Bucket=os.environ["S3_BUCKET"], Key=s3_key)
        assert obj["Body"].read() == sample_image_bytes

    def test_upload_no_file_returns_422(self, api_client):
        resp = api_client.post("/upload")
        assert resp.status_code == 422


class TestDocumentsEndpoint:
    """Test GET /documents endpoint."""

    def test_list_empty(self, api_client):
        resp = api_client.get("/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_list_after_upload(self, api_client, sample_image_bytes):
        api_client.post(
            "/upload",
            files={"file": ("listed.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

        docs = api_client.get("/documents").json()["documents"]
        assert len(docs) >= 1
        assert any(d["original_filename"] == "listed.png" for d in docs)

    def test_list_returns_expected_fields(self, api_client, sample_image_bytes):
        api_client.post(
            "/upload",
            files={"file": ("fields.png", io.BytesIO(sample_image_bytes), "image/png")},
        )

        doc = api_client.get("/documents").json()["documents"][0]
        for field in ["doc_id", "original_filename", "content_type", "ocr_status", "created_at"]:
            assert field in doc, f"Missing field: {field}"


class TestDocumentDetailEndpoint:
    """Test GET /documents/{doc_id} and /documents/{doc_id}/text."""

    def test_get_existing_document(self, api_client, sample_image_bytes):
        doc_id = api_client.post(
            "/upload", files={"file": ("detail.png", io.BytesIO(sample_image_bytes), "image/png")},
        ).json()["doc_id"]

        resp = api_client.get(f"/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id
        assert data["original_filename"] == "detail.png"
        assert data["ocr_status"] == "pending"

    def test_get_nonexistent_document(self, api_client):
        resp = api_client.get(f"/documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_document_text_pending(self, api_client, sample_image_bytes):
        doc_id = api_client.post(
            "/upload", files={"file": ("text.png", io.BytesIO(sample_image_bytes), "image/png")},
        ).json()["doc_id"]

        resp = api_client.get(f"/documents/{doc_id}/text")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["text"] is None


class TestOCRProcessEndpoint:
    """Test POST /ocr/process endpoint."""

    def test_process_image(self, api_client, sample_image_bytes):
        doc_id = api_client.post(
            "/upload", files={"file": ("ocr_me.png", io.BytesIO(sample_image_bytes), "image/png")},
        ).json()["doc_id"]

        resp = api_client.post("/ocr/process", json={"doc_id": doc_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id
        assert data["status"] == "completed"
        assert data["page_count"] == 1
        assert data["word_count"] >= 0
        assert "s3_key_text" in data

    def test_process_updates_db(self, api_client, sample_image_bytes):
        doc_id = api_client.post(
            "/upload", files={"file": ("db_check.png", io.BytesIO(sample_image_bytes), "image/png")},
        ).json()["doc_id"]

        api_client.post("/ocr/process", json={"doc_id": doc_id})

        detail = api_client.get(f"/documents/{doc_id}").json()
        assert detail["ocr_status"] == "completed"
        assert detail["extracted_text"] is not None
        assert detail["s3_key_text"] is not None
        assert detail["processed_at"] is not None

    def test_process_saves_text_to_s3(self, api_client, s3_mock, sample_image_bytes):
        doc_id = api_client.post(
            "/upload", files={"file": ("s3_text.png", io.BytesIO(sample_image_bytes), "image/png")},
        ).json()["doc_id"]

        result = api_client.post("/ocr/process", json={"doc_id": doc_id}).json()
        text_key = result["s3_key_text"]

        obj = s3_mock.get_object(Bucket=os.environ["S3_BUCKET"], Key=text_key)
        assert isinstance(obj["Body"].read().decode("utf-8"), str)

    def test_process_nonexistent_doc(self, api_client):
        resp = api_client.post("/ocr/process", json={"doc_id": str(uuid.uuid4())})
        assert resp.status_code == 404

    def test_process_missing_doc_id(self, api_client):
        resp = api_client.post("/ocr/process", json={})
        assert resp.status_code == 422

    def test_extracted_text_endpoint_after_process(self, api_client, sample_image_bytes):
        doc_id = api_client.post(
            "/upload", files={"file": ("text_ep.png", io.BytesIO(sample_image_bytes), "image/png")},
        ).json()["doc_id"]

        api_client.post("/ocr/process", json={"doc_id": doc_id})

        data = api_client.get(f"/documents/{doc_id}/text").json()
        assert data["status"] == "completed"
        assert data["text"] is not None
        assert isinstance(data["text"], str)
