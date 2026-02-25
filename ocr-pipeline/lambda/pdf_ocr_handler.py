"""
PDF OCR Handler — Extracts images from PDF pages, then runs Tesseract OCR on each.

Flow:
  PDF → PyMuPDF renders each page as image → Tesseract OCR per image → combined text

Tracks timing at every stage:
  - Per page: image extraction time + OCR time
  - Total: overall pipeline time
"""

import base64
import os
import subprocess
import tempfile
import time

import fitz  # PyMuPDF


def run_tesseract(image_path: str) -> tuple[str, float]:
    """Run Tesseract OCR on an image file. Returns (text, elapsed_ms)."""
    start = time.time()
    result = subprocess.run(
        ["tesseract", image_path, "stdout", "--oem", "1", "--psm", "3"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed_ms = round((time.time() - start) * 1000, 2)
    text = result.stdout.strip()

    if result.returncode != 0 and not text:
        raise RuntimeError(f"Tesseract failed: {result.stderr.strip()}")

    return text, elapsed_ms


def extract_page_image(page, dpi: int = 300) -> tuple[bytes, float]:
    """Render a PDF page to a PNG image. Returns (png_bytes, elapsed_ms)."""
    start = time.time()
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    elapsed_ms = round((time.time() - start) * 1000, 2)
    return png_bytes, elapsed_ms


def pdf_ocr_handler(event, context):
    """
    PDF OCR Lambda handler.
    Receives base64-encoded PDF, extracts page images, OCRs each, returns combined text.
    """

    try:
        payload = event
        pdf_data = payload.get("pdf", "")
        filename = payload.get("filename", "unknown.pdf")
        dpi = payload.get("dpi", 300)

        if not pdf_data:
            return {"error": "No PDF data provided"}

        # Strip data URL prefix if present
        if "," in pdf_data:
            pdf_data = pdf_data.split(",", 1)[1]

        pdf_bytes = base64.b64decode(pdf_data)

        # Write PDF to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            pdf_path = tmp.name

        total_start = time.time()

        doc = fitz.open(pdf_path)
        page_count = len(doc)

        pages = []
        full_text_parts = []
        total_word_count = 0
        total_char_count = 0
        total_extract_ms = 0
        total_ocr_ms = 0

        for i, page in enumerate(doc):
            page_start = time.time()

            # Step 1: Render page to image
            png_bytes, extract_ms = extract_page_image(page, dpi)
            total_extract_ms += extract_ms

            # Write image to temp file for Tesseract
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_tmp:
                img_tmp.write(png_bytes)
                img_path = img_tmp.name

            # Step 2: OCR the rendered image
            text, ocr_ms = run_tesseract(img_path)
            total_ocr_ms += ocr_ms

            # Clean up temp image
            os.unlink(img_path)

            page_total_ms = round((time.time() - page_start) * 1000, 2)

            word_count = len(text.split()) if text else 0
            char_count = len(text)
            total_word_count += word_count
            total_char_count += char_count
            full_text_parts.append(text)

            pages.append({
                "page": i + 1,
                "text": text,
                "word_count": word_count,
                "char_count": char_count,
                "image_extract_ms": extract_ms,
                "ocr_ms": ocr_ms,
                "page_total_ms": page_total_ms,
                "image_size_bytes": len(png_bytes),
            })

        doc.close()
        os.unlink(pdf_path)

        pipeline_ms = round((time.time() - total_start) * 1000, 2)
        full_text = "\n\n".join(full_text_parts)

        return {
            "text": full_text,
            "filename": filename,
            "page_count": page_count,
            "total_word_count": total_word_count,
            "total_char_count": total_char_count,
            "timing": {
                "pipeline_ms": pipeline_ms,
                "total_image_extract_ms": round(total_extract_ms, 2),
                "total_ocr_ms": round(total_ocr_ms, 2),
                "avg_extract_per_page_ms": round(total_extract_ms / max(page_count, 1), 2),
                "avg_ocr_per_page_ms": round(total_ocr_ms / max(page_count, 1), 2),
            },
            "pdf_size_bytes": len(pdf_bytes),
            "dpi": dpi,
            "pages": pages,
        }

    except Exception as e:
        return {"error": str(e)}
