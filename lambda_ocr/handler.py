"""Lambda function: OCR text extraction from a base64-encoded image using Tesseract."""

import base64
import json
import subprocess
import tempfile
import time
import os


def handler(event, context):
    """Receive base64 image, run Tesseract, return extracted text + timing."""
    start = time.time()

    body = event
    if isinstance(event.get("body"), str):
        body = json.loads(event["body"])

    image_b64 = body.get("image_b64", "")
    image_ext = body.get("image_ext", "png")
    image_name = body.get("image_name", "unknown")

    if not image_b64:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No image_b64 provided"}),
        }

    try:
        img_bytes = base64.b64decode(image_b64)

        with tempfile.NamedTemporaryFile(suffix=f".{image_ext}", delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        out_base = tmp_path + "_out"
        result = subprocess.run(
            ["tesseract", tmp_path, out_base, "-l", "eng", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        out_txt_path = out_base + ".txt"
        text = ""
        if os.path.exists(out_txt_path):
            with open(out_txt_path, "r") as f:
                text = f.read().strip()
            os.unlink(out_txt_path)

        os.unlink(tmp_path)

        elapsed_ms = round((time.time() - start) * 1000, 2)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "image_name": image_name,
                "text": text,
                "elapsed_ms": elapsed_ms,
                "tesseract_stderr": result.stderr.strip() if result.stderr else "",
            }),
        }

    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "image_name": image_name,
                "elapsed_ms": elapsed_ms,
            }),
        }
