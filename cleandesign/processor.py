import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict

from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("document-processors")


def download_s3_file(s3_client, bucket_name: str, object_key: str, document_id: str) -> str:
    """
    Downloads the S3 object to a temp directory and returns the local file path.
    """
    temp_dir = tempfile.mkdtemp(prefix=f"doc_{document_id}_")
    filename = Path(object_key).name or f"{document_id}.bin"
    local_path = os.path.join(temp_dir, filename)

    try:
        logger.info("Downloading s3://%s/%s -> %s", bucket_name, object_key, local_path)
        s3_client.download_file(bucket_name, object_key, local_path)
        return local_path
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Failed to download S3 file s3://{bucket_name}/{object_key}: {exc}"
        ) from exc


def ocr_file(file_path: str) -> str:
    """
    Placeholder OCR function.
    Replace with pytesseract, textract, paddleocr, easyocr, etc.
    """
    logger.info("OCR phase started for: %s", file_path)

    suffix = Path(file_path).suffix.lower()
    supported_image_types = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

    if suffix not in supported_image_types:
        raise RuntimeError(f"OCR not supported for file type: {suffix}")

    # Placeholder result
    return f"[OCR OUTPUT] Simulated OCR text extracted from image file: {Path(file_path).name}"


def extract_text(file_path: str) -> str:
    """
    Placeholder text extraction function.
    For plain text, CSV, JSON, etc.
    """
    logger.info("Text extraction phase started for: %s", file_path)

    suffix = Path(file_path).suffix.lower()
    supported_text_types = {".txt", ".csv", ".json", ".md", ".log"}

    if suffix not in supported_text_types:
        raise RuntimeError(f"Text extraction not supported for file type: {suffix}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Unable to decode text file: {file_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read file: {file_path}") from exc


def classify_processing_method(file_path: str, document_type: str) -> str:
    """
    Decide which processor to use.
    """
    suffix = Path(file_path).suffix.lower()

    image_types = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    text_types = {".txt", ".csv", ".json", ".md", ".log"}

    if suffix in image_types or document_type.startswith("image/"):
        return "ocr"

    if suffix in text_types or document_type.startswith("text/"):
        return "text_extract"

    # simple fallback
    return "text_extract"


def process_document_pipeline(file_path: str, document_type: str) -> Dict[str, str]:
    """
    End-to-end document processing orchestration.
    """
    logger.info("Pipeline start | file=%s | type=%s", file_path, document_type)

    method = classify_processing_method(file_path, document_type)
    text = ""

    if method == "ocr":
        text = ocr_file(file_path)
    elif method == "text_extract":
        text = extract_text(file_path)
    else:
        raise RuntimeError(f"Unsupported processing method: {method}")

    logger.info("Pipeline complete | method=%s", method)

    return {
        "method": method,
        "text": text,
    }


def cleanup_temp_file(file_path: str) -> None:
    """
    Remove temp directory containing the downloaded file.
    """
    try:
        temp_dir = str(Path(file_path).parent)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("Cleaned temp directory: %s", temp_dir)
    except Exception as exc:
        logger.warning("Temp cleanup failed for %s: %s", file_path, exc)