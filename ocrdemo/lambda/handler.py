import json
import base64
import time
import subprocess
import tempfile
import os


def lambda_handler(event, context):
    """OCR Lambda handler - extracts text from uploaded images via direct invocation."""

    try:
        # Support both direct invocation and API Gateway proxy
        if "body" in event and "httpMethod" in event:
            body = event.get("body", "")
            if event.get("isBase64Encoded", False):
                body = base64.b64decode(body).decode("utf-8")
            payload = json.loads(body) if isinstance(body, str) else body
        else:
            payload = event

        image_data = payload.get("image", "")
        filename = payload.get("filename", "unknown")

        if not image_data:
            return {"error": "No image data provided"}

        # Strip data URL prefix if present
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]

        # Decode image bytes
        image_bytes = base64.b64decode(image_data)

        # Write to temp file
        suffix = os.path.splitext(filename)[1] or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        # Run Tesseract OCR with timing
        start_time = time.time()

        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "--oem", "1", "--psm", "3"],
            capture_output=True,
            text=True,
            timeout=30
        )

        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        # Clean up temp file
        os.unlink(tmp_path)

        extracted_text = result.stdout.strip()

        if result.returncode != 0 and not extracted_text:
            return {
                "error": "Tesseract OCR failed: " + result.stderr.strip(),
                "processing_time_ms": elapsed_ms
            }

        return {
            "text": extracted_text,
            "processing_time_ms": elapsed_ms,
            "filename": filename,
            "text_length": len(extracted_text),
            "word_count": len(extracted_text.split()) if extracted_text else 0
        }

    except Exception as e:
        return {"error": str(e)}
