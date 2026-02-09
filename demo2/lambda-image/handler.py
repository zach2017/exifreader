"""
Lambda handler — extracts text from PDFs and images.

PDF:  PyPDF2 native text → fallback to pdf2image + Tesseract OCR.
TIFF: Pillow multi-frame + Tesseract OCR.
PNG/JPG: Tesseract OCR.
"""

import json
import time
import base64
import io
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    t0 = time.perf_counter()

    try:
        file_data = base64.b64decode(event["file_data"])
        file_type = event.get("file_type", "pdf").lower()
        file_name = event.get("file_name", "upload")

        logger.info("Processing %s (%s, %d bytes)", file_name, file_type, len(file_data))

        if file_type == "pdf":
            text, pages = extract_from_pdf(file_data)
        elif file_type in ("tiff", "tif", "png", "jpg", "jpeg"):
            text = extract_from_image(file_data)
            pages = 1
        else:
            return _resp(400, error=f"Unsupported type: {file_type}")

        ms = round((time.perf_counter() - t0) * 1000)
        logger.info("Done: %d chars, %d pages, %d ms", len(text), pages, ms)
        return _resp(200, text=text.strip(), pages=pages, processing_time_ms=ms)

    except Exception as exc:
        logger.exception("Extraction failed")
        ms = round((time.perf_counter() - t0) * 1000)
        return _resp(500, error=str(exc), processing_time_ms=ms)


def extract_from_pdf(data: bytes):
    import PyPDF2
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    pages = len(reader.pages)
    parts = [page.extract_text() or "" for page in reader.pages]
    combined = "\n\n".join(parts)
    if combined.strip() and len(combined.strip()) > 20:
        return combined, pages
    logger.info("No native text — falling back to OCR (%d pages)", pages)
    return _ocr_pdf(data), pages


def _ocr_pdf(data: bytes):
    from pdf2image import convert_from_bytes
    import pytesseract
    images = convert_from_bytes(data, dpi=300)
    parts = []
    for i, img in enumerate(images):
        logger.info("OCR page %d/%d", i + 1, len(images))
        parts.append(f"--- Page {i+1} ---\n{pytesseract.image_to_string(img, lang='eng')}")
    return "\n\n".join(parts)


def extract_from_image(data: bytes):
    from PIL import Image
    import pytesseract
    img = Image.open(io.BytesIO(data))
    frames = []
    try:
        while True:
            frames.append(img.copy())
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    if not frames:
        frames = [img]
    parts = []
    for i, f in enumerate(frames):
        if f.mode not in ("RGB", "L"):
            f = f.convert("RGB")
        t = pytesseract.image_to_string(f, lang="eng")
        parts.append(f"--- Frame {i+1} ---\n{t}" if len(frames) > 1 else t)
    return "\n\n".join(parts)


def _resp(code, **body):
    return {"statusCode": code, "body": json.dumps(body)}
