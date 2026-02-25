import base64
import os
import tempfile
import time

import fitz  # PyMuPDF


def pdf_handler(event, context):
    """PDF Lambda handler - extracts text from uploaded PDF files with per-page timing."""

    try:
        payload = event
        pdf_data = payload.get("pdf", "")
        filename = payload.get("filename", "unknown.pdf")

        if not pdf_data:
            return {"error": "No PDF data provided"}

        # Strip data URL prefix if present
        if "," in pdf_data:
            pdf_data = pdf_data.split(",", 1)[1]

        pdf_bytes = base64.b64decode(pdf_data)

        # Write to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        # Extract text with timing
        total_start = time.time()

        doc = fitz.open(tmp_path)
        page_count = len(doc)

        pages = []
        full_text_parts = []
        total_word_count = 0
        total_char_count = 0

        for i, page in enumerate(doc):
            page_start = time.time()
            text = page.get_text("text").strip()
            page_ms = round((time.time() - page_start) * 1000, 2)

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
                "extraction_time_ms": page_ms,
            })

        doc.close()

        total_ms = round((time.time() - total_start) * 1000, 2)

        # Clean up
        os.unlink(tmp_path)

        full_text = "\n\n".join(full_text_parts)

        return {
            "text": full_text,
            "filename": filename,
            "page_count": page_count,
            "total_word_count": total_word_count,
            "total_char_count": total_char_count,
            "processing_time_ms": total_ms,
            "file_size_bytes": len(pdf_bytes),
            "pages": pages,
        }

    except Exception as e:
        return {"error": str(e)}
