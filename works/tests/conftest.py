"""
Shared pytest fixtures for the OCR solution test suite.

Provides:
  - Mocked S3 (via moto) for all S3 tests
  - Real Postgres connection (skips if unavailable)
  - FastAPI test client with S3 mocked and Postgres wired
  - Sample image bytes for upload tests
"""

import io
import os
import sys
import uuid

import boto3
import psycopg2
import pytest
from moto import mock_aws
from PIL import Image, ImageDraw

# ── Add source directories to path ────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api-server"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))

# ── Environment Setup ─────────────────────────
# Set env vars BEFORE importing the app so Settings picks them up

TEST_BUCKET = "test-ocr-documents"

os.environ.update({
    "AWS_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "S3_ENDPOINT": "",  # Empty = use moto's mock, not LocalStack
    "S3_BUCKET": TEST_BUCKET,
    "POSTGRES_HOST": os.environ.get("POSTGRES_HOST", "localhost"),
    "POSTGRES_PORT": os.environ.get("POSTGRES_PORT", "5432"),
    "POSTGRES_DB": os.environ.get("POSTGRES_DB", "ocr_db"),
    "POSTGRES_USER": os.environ.get("POSTGRES_USER", "ocruser"),
    "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD", "ocrpass123"),
})


# ── Helpers ───────────────────────────────────

def create_test_image(text: str = "Hello OCR", width: int = 400, height: int = 100) -> Image.Image:
    """Create a simple test image with text for OCR testing."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), text, fill="black")
    return img


def image_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    """Convert a PIL Image to bytes."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.getvalue()


# ── S3 Fixtures ───────────────────────────────

@pytest.fixture
def aws_credentials():
    """Mocked AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def s3_client(aws_credentials):
    """Mocked S3 client with test bucket created."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=TEST_BUCKET)

        response = client.list_buckets()
        bucket_names = [b["Name"] for b in response["Buckets"]]
        assert TEST_BUCKET in bucket_names

        yield client


@pytest.fixture
def s3_with_test_image(s3_client):
    """S3 client with a test image already uploaded."""
    doc_id = str(uuid.uuid4())
    filename = "test-image.png"
    s3_key = f"uploads/{doc_id}/{filename}"

    img = create_test_image("Hello World OCR Test")
    img_bytes = image_to_bytes(img)

    s3_client.put_object(
        Bucket=TEST_BUCKET,
        Key=s3_key,
        Body=img_bytes,
        ContentType="image/png",
    )

    return {
        "client": s3_client,
        "doc_id": doc_id,
        "s3_key": s3_key,
        "filename": filename,
        "image_bytes": img_bytes,
    }


# ── Postgres Fixtures ─────────────────────────

def _try_connect_postgres():
    """Attempt a Postgres connection, return conn or None."""
    try:
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            dbname=os.environ.get("POSTGRES_DB", "ocr_db"),
            user=os.environ.get("POSTGRES_USER", "ocruser"),
            password=os.environ.get("POSTGRES_PASSWORD", "ocrpass123"),
        )
        return conn
    except psycopg2.OperationalError:
        return None


@pytest.fixture
def db_conn():
    """
    Real Postgres connection. Skips if Postgres unavailable.
    Uses a transaction that is rolled back after each test.
    """
    conn = _try_connect_postgres()
    if conn is None:
        pytest.skip("Postgres not available")

    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def clean_db(db_conn):
    """Clean the documents and processing_log tables before each test."""
    cur = db_conn.cursor()
    cur.execute("DELETE FROM processing_log")
    cur.execute("DELETE FROM documents")
    db_conn.commit()
    yield db_conn
    db_conn.rollback()


# ── Sample Image ──────────────────────────────

@pytest.fixture
def sample_image_bytes():
    """Generate a test PNG image with readable text."""
    img = create_test_image("SAMPLE OCR TEXT 12345", width=500, height=120)
    return image_to_bytes(img)


# ── S3 Mock (session-level moto context for API tests) ──

@pytest.fixture
def s3_mock():
    """
    A moto-mocked S3 client available to API integration tests.
    Patches the module-level get_s3_client in main so the FastAPI app uses moto.
    """
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=TEST_BUCKET)
        yield client


# ── FastAPI Test Client ───────────────────────

@pytest.fixture
def api_client(s3_mock):
    """
    FastAPI test client with S3 mocked via moto.
    Requires Postgres to be running — skips otherwise.
    """
    # Check postgres first
    conn = _try_connect_postgres()
    if conn is None:
        pytest.skip("Postgres not available — API integration tests require it")
    conn.close()

    from unittest.mock import patch
    from main import app

    # Patch get_s3_client to always return the moto mock
    def _mock_s3():
        return s3_mock

    with patch("main.get_s3_client", side_effect=_mock_s3):
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            yield client
