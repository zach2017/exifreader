"""
Document Processors – Memory-Optimised Edition
===============================================
Every function is designed for 1 GB+ PDFs in a RAM-constrained container.

Design principles
-----------------
1.  **Page-at-a-time processing** – PyMuPDF page objects are loaded, used,
    and immediately released.  `del page; gc.collect()` after each iteration.
2.  **Streaming writes** – extracted text is appended to a temp file on disk,
    never accumulated in an in-memory string.
3.  **Chunked S3 downloads** – the source file is streamed in 8 MB chunks;
    at no point is the full object held in RAM.
4.  **Image extraction with immediate upload** – each image is written to a
    temp file, uploaded to S3, and deleted before the next image.
5.  **Aggressive cleanup** – temp dirs, file handles, and large locals are
    deleted explicitly; `gc.collect()` runs after heavy work.
"""

import gc
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

import fitz  # PyMuPDF — backed by MuPDF C library

from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("document-processors")

# ── Memory-tuning constants ──────────────────────────────────────────────
_PAGE_LOG_INTERVAL = 50          # log progress every N pages
_S3_UPLOAD_EXTRA_ARGS: dict = {} # e.g. {"ServerSideEncryption": "AES256"}


# =========================================================================
# S3 Download – chunked streaming
# =========================================================================

def download_s3_file_streaming(
    s3_client,
    bucket_name: str,
    object_key: str,
    document_id: str,
    tmp_root: str = "/tmp/docworker",
    chunk_size: int = 8 * 1024 * 1024,
) -> str:
    """
    Download an S3 object in *chunk_size* byte increments so that only one
    chunk is in RAM at a time.  Returns the local file path.
    """
    os.makedirs(tmp_root, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix=f"doc_{document_id}_", dir=tmp_root)
    filename = Path(object_key).name or f"{document_id}.bin"
    local_path = os.path.join(tmp_dir, filename)

    try:
        logger.info("Streaming download s3://%s/%s -> %s", bucket_name, object_key, local_path)
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        body = response["Body"]

        with open(local_path, "wb") as fp:
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    break
                fp.write(chunk)
                # chunk is overwritten on next iter → old one is GC-able

        body.close()
        logger.info("Download complete: %s (%.2f MB)", local_path, os.path.getsize(local_path) / 1e6)
        return local_path

    except (ClientError, BotoCoreError) as exc:
        # Clean up partial file on failure
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(
            f"Failed to download s3://{bucket_name}/{object_key}: {exc}"
        ) from exc


# =========================================================================
# Text extraction – page-by-page streaming to disk
# =========================================================================

def extract_text_streamed(
    file_path: str,
    tmp_root: str = "/tmp/docworker",
    document_id: str = "unknown",
) -> str:
    """
    Open a PDF and extract text **one page at a time**, appending each page's
    text to a temporary file on disk.  Returns the path to the text file.

    Peak RAM ≈ size of one page's text + PyMuPDF page object overhead.
    """
    logger.info("Streamed text extraction started: %s", file_path)

    os.makedirs(tmp_root, exist_ok=True)
    out_path = os.path.join(tmp_root, f"{document_id}_extracted.txt")

    doc = None
    try:
        doc = fitz.open(file_path)
        total_pages = doc.page_count
        logger.info("PDF has %d pages", total_pages)

        with open(out_path, "w", encoding="utf-8") as out_fp:
            for page_num in range(total_pages):
                page = doc.load_page(page_num)
                text = page.get_text("text")      # extract as plain text
                if text:
                    out_fp.write(text)
                    out_fp.write("\n")             # page separator

                # ── Release page memory immediately ──
                del text
                del page

                if (page_num + 1) % _PAGE_LOG_INTERVAL == 0:
                    logger.info("  … extracted %d / %d pages", page_num + 1, total_pages)

        logger.info("Text extraction complete -> %s", out_path)
        return out_path

    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Unable to decode: {file_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read: {file_path}") from exc
    finally:
        if doc:
            doc.close()
            del doc
        gc.collect()


# =========================================================================
# Image extraction – page-by-page, upload-and-delete
# =========================================================================

def extract_pdf_images_streamed(
    local_path: str,
    payload: Dict[str, Any],
    s3_client,
    s3_bucket: str,
    tmp_root: str = "/tmp/docworker",
) -> int:
    """
    Extract images from a PDF **one page at a time**.  Each image is:
      1. Written to a temp file on disk
      2. Uploaded to S3
      3. Immediately deleted from disk

    This keeps peak RAM at roughly the size of one image regardless of the
    total number of images in the document.
    """
    logger.info("Streamed image extraction started: %s", local_path)

    os.makedirs(tmp_root, exist_ok=True)
    img_tmp_dir = tempfile.mkdtemp(prefix="img-extract-", dir=tmp_root)

    doc = None
    img_count = 0

    try:
        doc = fitz.open(local_path)
        total_pages = doc.page_count

        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            image_list = page.get_images(full=True)

            for img_index, img_ref in enumerate(image_list):
                xref = img_ref[0]

                try:
                    base_image = doc.extract_image(xref)
                except Exception as exc:
                    logger.warning(
                        "Skipping corrupt image xref=%d page=%d: %s", xref, page_num, exc
                    )
                    continue

                image_bytes = base_image["image"]
                ext = base_image.get("ext", "png")

                # Write to temp file
                img_filename = f"img_{page_num}_{img_index}.{ext}"
                local_img_path = os.path.join(img_tmp_dir, img_filename)

                with open(local_img_path, "wb") as f:
                    f.write(image_bytes)

                # Free the bytes from RAM immediately
                del image_bytes
                del base_image

                # Upload to S3
                img_s3_key = f"{payload['documentId']}_ext_{img_filename}"
                try:
                    s3_client.upload_file(
                        local_img_path, s3_bucket, img_s3_key, ExtraArgs=_S3_UPLOAD_EXTRA_ARGS
                    )
                except (ClientError, BotoCoreError) as exc:
                    logger.error("Failed to upload image %s: %s", img_s3_key, exc)

                # Delete temp image file immediately
                os.remove(local_img_path)
                img_count += 1

            # ── Release page memory ──
            del page
            del image_list

            if (page_num + 1) % _PAGE_LOG_INTERVAL == 0:
                logger.info("  … scanned %d / %d pages for images", page_num + 1, total_pages)

        logger.info("Image extraction complete: %d images found", img_count)
        return img_count

    finally:
        if doc:
            doc.close()
            del doc
        shutil.rmtree(img_tmp_dir, ignore_errors=True)
        gc.collect()


# =========================================================================
# OCR placeholder
# =========================================================================

def ocr_file(file_path: str) -> str:
    logger.info("OCR phase started: %s", file_path)
    suffix = Path(file_path).suffix.lower()
    supported = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    if suffix not in supported:
        raise RuntimeError(f"OCR not supported for: {suffix}")
    return f"[OCR placeholder] {Path(file_path).name}"


# =========================================================================
# Processing router
# =========================================================================

def _classify_method(document_type: str) -> str:
    dt = document_type.upper()
    if dt in ("PDF", "TXT"):
        return "text_extract"
    return "ocr"


def process_document_pipeline(
    file_path: str,
    document_type: str,
    tmp_root: str = "/tmp/docworker",
    document_id: str = "unknown",
) -> Dict[str, str]:
    """
    Route the file to the correct processor and return
    {"method": ..., "text": <path_to_text_file>}.
    """
    logger.info("Pipeline start | file=%s type=%s", file_path, document_type)

    method = _classify_method(document_type)

    if method == "text_extract":
        text_path = extract_text_streamed(
            file_path, tmp_root=tmp_root, document_id=document_id
        )
    elif method == "ocr":
        text_path = ocr_file(file_path)
    else:
        raise RuntimeError(f"Unsupported method: {method}")

    logger.info("Pipeline complete | method=%s", method)
    return {"method": method, "text": text_path}


# =========================================================================
# Cleanup
# =========================================================================

def cleanup_temp_file(file_path: str) -> None:
    """Remove the temp directory that contains *file_path*."""
    try:
        temp_dir = str(Path(file_path).parent)
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("Cleaned temp dir: %s", temp_dir)
    except Exception as exc:
        logger.warning("Cleanup failed for %s: %s", file_path, exc)
