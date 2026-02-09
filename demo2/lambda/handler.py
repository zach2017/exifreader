"""
Lambda handler — PDF & image text extraction via Tesseract OCR.

Tesseract + Poppler binaries come from a Lambda Layer at /opt.
"""

import os
import sys
import json
import time
import base64
import io
import logging
import subprocess

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Layer paths (/opt is where Lambda Layers extract to) ──
os.environ["PATH"] = "/opt/bin:" + os.environ.get("PATH", "")
os.environ["LD_LIBRARY_PATH"] = "/opt/lib:" + os.environ.get("LD_LIBRARY_PATH", "")
os.environ["TESSDATA_PREFIX"] = os.environ.get("TESSDATA_PREFIX", "/opt/share/tessdata")


def _log_setup():
    try:
        r = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=5)
        logger.info("tesseract: %s", (r.stdout or r.stderr).split("\n")[0])
    except Exception as e:
        logger.error("tesseract not found: %s", e)
        for d in ["/opt", "/opt/bin", "/opt/lib", "/opt/share"]:
            if os.path.isdir(d):
                logger.info("  %s → %s", d, os.listdir(d)[:15])

_log_setup()


def handler(event, context):
    t0 = time.perf_counter()
    try:
        file_data = base64.b64decode(event["file_data"])
        file_type = event.get("file_type", "pdf").lower()
        file_name = event.get("file_name", "upload")
        logger.info("Processing %s (%s, %d bytes)", file_name, file_type, len(file_data))

        if file_type == "pdf":
            text, pages = _extract_pdf(file_data)
        elif file_type in ("tiff", "tif", "png", "jpg", "jpeg"):
            text = _extract_image(file_data)
            pages = 1
        else:
            return _resp(400, error="Unsupported type: " + file_type)

        ms = round((time.perf_counter() - t0) * 1000)
        logger.info("Done: %d chars, %d pages, %d ms", len(text), pages, ms)
        return _resp(200, text=text.strip(), pages=pages, processing_time_ms=ms)
    except Exception as exc:
        logger.exception("Extraction failed")
        return _resp(500, error=str(exc), processing_time_ms=round((time.perf_counter() - t0) * 1000))


def _extract_pdf(data):
    import PyPDF2
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    pages = len(reader.pages)
    parts = [p.extract_text() or "" for p in reader.pages]
    combined = "\n\n".join(parts)
    if combined.strip() and len(combined.strip()) > 20:
        return combined, pages
    logger.info("No native text — OCR fallback (%d pages)", pages)
    return _ocr_pdf(data), pages


def _ocr_pdf(data):
    from pdf2image import convert_from_bytes
    import pytesseract
    images = convert_from_bytes(data, dpi=300)
    parts = []
    for i, img in enumerate(images):
        logger.info("OCR page %d/%d", i + 1, len(images))
        parts.append("--- Page %d ---\n%s" % (i + 1, pytesseract.image_to_string(img, lang="eng")))
    return "\n\n".join(parts)


def _extract_image(data):
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
        parts.append("--- Frame %d ---\n%s" % (i + 1, t) if len(frames) > 1 else t)
    return "\n\n".join(parts)


def _resp(code, **body):
    return {"statusCode": code, "body": json.dumps(body)}
