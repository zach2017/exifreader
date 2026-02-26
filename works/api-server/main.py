"""
OCR API Server
─────────────────────────────────────────────
Receives document IDs from Lambda, pulls files from S3,
runs Tesseract OCR, saves text to S3 + Postgres.
"""

import io
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import boto3
import psycopg2
import psycopg2.extras
import pytesseract
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pdf2image import convert_from_bytes
from PIL import Image
from pydantic import BaseModel
from pydantic_settings import BaseSettings

# ── Config ────────────────────────────────────

class Settings(BaseSettings):
    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    s3_endpoint: str = "http://localstack:4566"
    s3_bucket: str = "ocr-documents"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "ocr_db"
    postgres_user: str = "ocruser"
    postgres_password: str = "ocrpass123"

settings = Settings()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ocr-api")

app = FastAPI(title="OCR API Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AWS S3 Client ─────────────────────────────

def get_s3_client():
    kwargs = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.s3_endpoint:
        kwargs["endpoint_url"] = settings.s3_endpoint
    return boto3.client("s3", **kwargs)


def ensure_bucket_exists():
    """Create the S3 bucket if it does not already exist."""
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
        logger.info(f"S3 bucket '{settings.s3_bucket}' already exists")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            logger.info(f"Creating S3 bucket '{settings.s3_bucket}'")
            create_kwargs = {"Bucket": settings.s3_bucket}
            if settings.aws_region != "us-east-1":
                create_kwargs["CreateBucketConfiguration"] = {
                    "LocationConstraint": settings.aws_region
                }
            client.create_bucket(**create_kwargs)
            # Verify creation
            client.head_bucket(Bucket=settings.s3_bucket)
            logger.info(f"S3 bucket '{settings.s3_bucket}' created successfully")
        else:
            raise


# ── Postgres Connection ───────────────────────

@contextmanager
def get_db():
    """Context manager for Postgres connections."""
    conn = psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
    try:
        yield conn
    finally:
        conn.close()


def log_processing(doc_id: str, stage: str, status: str, message: str = ""):
    """Write an entry to the processing_log audit trail."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO processing_log (doc_id, stage, status, message) VALUES (%s, %s, %s, %s)",
                    (doc_id, stage, status, message),
                )
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to log processing: {e}")


# ── OCR Logic ─────────────────────────────────

def ocr_image(image: Image.Image) -> str:
    """Run Tesseract on a single PIL Image."""
    return pytesseract.image_to_string(image, lang="eng")


def ocr_file(file_bytes: bytes, content_type: str) -> tuple[str, int]:
    """OCR a file and return (text, page_count)."""
    if content_type == "application/pdf":
        images = convert_from_bytes(file_bytes, dpi=300)
        texts = [ocr_image(img) for img in images]
        return "\n\n--- Page Break ---\n\n".join(texts), len(images)
    else:
        img = Image.open(io.BytesIO(file_bytes))
        return ocr_image(img), 1


# ── Models ────────────────────────────────────

class OCRRequest(BaseModel):
    doc_id: str

class UploadResponse(BaseModel):
    doc_id: str
    message: str


# ── Routes ────────────────────────────────────

@app.get("/health")
def health():
    """Health check — reports status of each dependency."""
    checks = {}

    # Tesseract
    try:
        ver = pytesseract.get_tesseract_version()
        checks["tesseract"] = {
            "status": "ok",
            "version": ver.decode().strip() if isinstance(ver, bytes) else str(ver).strip(),
        }
    except Exception as e:
        checks["tesseract"] = {"status": "error", "error": str(e)}

    # S3
    try:
        s3 = get_s3_client()
        s3.head_bucket(Bucket=settings.s3_bucket)
        checks["s3"] = {"status": "ok", "bucket": settings.s3_bucket}
    except Exception as e:
        checks["s3"] = {"status": "error", "error": str(e)}

    # Postgres
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        checks["postgres"] = {"status": "ok"}
    except Exception as e:
        checks["postgres"] = {"status": "error", "error": str(e)}

    overall = "ok" if all(c.get("status") == "ok" for c in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


@app.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a document to S3 and register it in Postgres."""
    doc_id = str(uuid.uuid4())
    file_bytes = await file.read()
    s3_key = f"uploads/{doc_id}/{file.filename}"

    s3 = get_s3_client()
    ensure_bucket_exists()

    # Upload to S3
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=s3_key,
        Body=file_bytes,
        ContentType=file.content_type,
    )

    # Register in Postgres
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO documents (doc_id, original_filename, s3_key_original, content_type, file_size_bytes, ocr_status)
                   VALUES (%s, %s, %s, %s, %s, 'pending')""",
                (doc_id, file.filename, s3_key, file.content_type, len(file_bytes)),
            )
            conn.commit()

    log_processing(doc_id, "upload", "completed", f"Uploaded {file.filename} ({len(file_bytes)} bytes)")
    return UploadResponse(doc_id=doc_id, message="Document uploaded successfully")


@app.post("/ocr/process")
def process_ocr(req: OCRRequest):
    """Called by Lambda – pull file from S3, OCR it, save text to S3 + Postgres."""
    doc_id = req.doc_id
    logger.info(f"Processing OCR for doc_id={doc_id}")

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

            cur.execute(
                "UPDATE documents SET ocr_status = 'processing' WHERE doc_id = %s",
                (doc_id,),
            )
            conn.commit()

    log_processing(doc_id, "ocr", "processing", "Started OCR processing")

    try:
        s3 = get_s3_client()
        s3_obj = s3.get_object(Bucket=settings.s3_bucket, Key=doc["s3_key_original"])
        file_bytes = s3_obj["Body"].read()

        extracted_text, page_count = ocr_file(file_bytes, doc["content_type"] or "image/png")
        word_count = len(extracted_text.split())

        text_key = f"text/{doc_id}/extracted.txt"
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=text_key,
            Body=extracted_text.encode("utf-8"),
            ContentType="text/plain",
        )

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE documents
                       SET extracted_text = %s,
                           s3_key_text = %s,
                           ocr_status = 'completed',
                           page_count = %s,
                           word_count = %s,
                           processed_at = NOW()
                       WHERE doc_id = %s""",
                    (extracted_text, text_key, page_count, word_count, doc_id),
                )
                conn.commit()

        log_processing(doc_id, "ocr", "completed", f"Extracted {word_count} words from {page_count} page(s)")

        return {
            "doc_id": doc_id,
            "status": "completed",
            "page_count": page_count,
            "word_count": word_count,
            "s3_key_text": text_key,
        }

    except Exception as e:
        logger.error(f"OCR failed for {doc_id}: {e}")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE documents SET ocr_status = 'failed', error_message = %s WHERE doc_id = %s",
                    (str(e), doc_id),
                )
                conn.commit()
        log_processing(doc_id, "ocr", "failed", str(e))
        return {"doc_id": doc_id, "status": "failed", "error": str(e)}


@app.get("/documents")
def list_documents():
    """List all documents."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT doc_id, original_filename, content_type, file_size_bytes,
                          ocr_status, word_count, page_count, created_at, processed_at
                   FROM documents ORDER BY created_at DESC LIMIT 100"""
            )
            rows = cur.fetchall()

    for r in rows:
        for k in ("created_at", "processed_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
    return {"documents": rows}


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    """Get full document details including extracted text."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
            doc = cur.fetchone()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    for k in ("created_at", "updated_at", "processed_at"):
        if doc.get(k):
            doc[k] = doc[k].isoformat()
    doc.pop("id", None)
    return doc


@app.get("/documents/{doc_id}/text")
def get_document_text(doc_id: str):
    """Return just the extracted text."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT doc_id, extracted_text, ocr_status FROM documents WHERE doc_id = %s",
                (doc_id,),
            )
            doc = cur.fetchone()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc["doc_id"], "status": doc["ocr_status"], "text": doc["extracted_text"]}
