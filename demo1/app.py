#!/usr/bin/env python3
"""Flask backend for PDF metadata + image extraction + OCR benchmarking."""

import os
import io
import json
import uuid
import time
import base64
import shutil
import logging
import concurrent.futures

import fitz  # PyMuPDF
import boto3
import pytesseract
from PIL import Image as PILImage
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

UPLOAD_DIR = "/data/uploads"
EXTRACT_DIR = "/data/extracted"
ALLOWED_EXTENSIONS = {"pdf"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)

# AWS / LocalStack config
LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localstack:4566")
LAMBDA_FUNCTION_NAME = os.environ.get("LAMBDA_FUNCTION_NAME", "ocr-extract-text")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

lambda_client = None


def get_lambda_client():
    global lambda_client
    if lambda_client is None:
        lambda_client = boto3.client(
            "lambda",
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name=AWS_REGION,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
    return lambda_client


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/extract", methods=["POST"])
def extract_pdf():
    """Upload a PDF, extract metadata, custom JSON fields, and all images."""

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file. PDF only."}), 400

    # Create unique job directory
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(EXTRACT_DIR, job_id)
    images_dir = os.path.join(job_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # Save uploaded PDF
    safe_name = secure_filename(file.filename)
    pdf_path = os.path.join(job_dir, safe_name)
    file.save(pdf_path)

    try:
        doc = fitz.open(pdf_path)

        # ── Standard metadata ──
        meta = doc.metadata or {}
        standard_metadata = {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "subject": meta.get("subject", ""),
            "keywords": meta.get("keywords", ""),
            "creator": meta.get("creator", ""),
            "producer": meta.get("producer", ""),
            "creationDate": meta.get("creationDate", ""),
            "modDate": meta.get("modDate", ""),
            "format": meta.get("format", ""),
            "encryption": meta.get("encryption") or "None",
            "pageCount": doc.page_count,
            "fileSize": os.path.getsize(pdf_path),
            "fileName": safe_name,
        }

        # ── Custom fields from /CustomFields JSON ──
        custom_fields = None
        try:
            with open(pdf_path, "rb") as f:
                raw = f.read().decode("latin1")

            marker = "/CustomFields"
            idx = raw.find(marker)
            if idx != -1:
                search_from = idx + len(marker)
                paren_start = raw.index("(", search_from)

                depth = 1
                content = []
                i = paren_start + 1
                while i < len(raw) and depth > 0:
                    ch = raw[i]
                    if ch == "\\" and i + 1 < len(raw):
                        nxt = raw[i + 1]
                        if "0" <= nxt <= "7":
                            octal = ""
                            j = i + 1
                            while j < len(raw) and j < i + 4 and "0" <= raw[j] <= "7":
                                octal += raw[j]
                                j += 1
                            content.append(chr(int(octal, 8)))
                            i = j
                            continue
                        esc_map = {
                            "(": "(", ")": ")", "\\": "\\",
                            "n": "\n", "r": "\r", "t": "\t",
                        }
                        content.append(esc_map.get(nxt, nxt))
                        i += 2
                        continue
                    if ch == "(":
                        depth += 1
                        content.append(ch)
                    elif ch == ")":
                        depth -= 1
                        if depth > 0:
                            content.append(ch)
                    else:
                        content.append(ch)
                    i += 1

                custom_fields = json.loads("".join(content))
        except Exception as e:
            app.logger.warning("Could not extract custom fields: %s", e)

        # ── Image extraction ──
        extracted_images = []
        img_counter = 0

        for page_num in range(doc.page_count):
            page = doc[page_num]
            image_list = page.get_images(full=True)

            for img_idx, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue

                    img_bytes = base_image["image"]
                    img_ext = base_image.get("ext", "png")
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    colorspace = base_image.get("colorspace", 0)
                    bpc = base_image.get("bpc", 0)
                    img_size = len(img_bytes)

                    if img_size < 100:
                        continue

                    img_counter += 1
                    img_filename = f"page{page_num + 1}_img{img_counter}.{img_ext}"
                    img_path = os.path.join(images_dir, img_filename)

                    with open(img_path, "wb") as f:
                        f.write(img_bytes)

                    extracted_images.append({
                        "filename": img_filename,
                        "page": page_num + 1,
                        "width": width,
                        "height": height,
                        "colorspace": colorspace,
                        "bpc": bpc,
                        "size": img_size,
                        "ext": img_ext,
                        "url": f"/api/images/{job_id}/{img_filename}",
                    })
                except Exception as e:
                    app.logger.warning(
                        "Failed to extract image xref=%s page=%s: %s",
                        xref, page_num, e,
                    )

        # ── Extract text directly from PDF (PyMuPDF built-in) ──
        pdf_text_pages = []
        for page_num in range(doc.page_count):
            page = doc[page_num]
            pdf_text_pages.append(page.get_text())

        doc.close()

        return jsonify({
            "jobId": job_id,
            "standardMetadata": standard_metadata,
            "customFields": custom_fields,
            "images": extracted_images,
            "imageCount": len(extracted_images),
            "pdfText": pdf_text_pages,
        })

    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500


# ──────────────────────────────────────────────
#  OCR Benchmark endpoint
# ──────────────────────────────────────────────

@app.route("/api/ocr/<job_id>", methods=["POST"])
def ocr_benchmark(job_id):
    """
    Run two OCR strategies and return timing comparison:
      1. Lambda per-image: invoke Lambda for each extracted image
      2. Direct Tesseract: OCR on each PDF page rendered as an image
    """
    safe_job = secure_filename(job_id)
    job_dir = os.path.join(EXTRACT_DIR, safe_job)
    images_dir = os.path.join(job_dir, "images")

    if not os.path.isdir(job_dir):
        return jsonify({"error": "Job not found"}), 404

    # Find the PDF
    pdf_path = None
    for f in os.listdir(job_dir):
        if f.endswith(".pdf"):
            pdf_path = os.path.join(job_dir, f)
            break

    if not pdf_path:
        return jsonify({"error": "PDF not found in job directory"}), 404

    results = {}

    # ────────────────────────────────────────
    #  Strategy 1: Lambda per-image OCR
    # ────────────────────────────────────────
    lambda_results = []
    lambda_total_start = time.time()
    lambda_errors = []

    if os.path.isdir(images_dir):
        image_files = sorted([
            f for f in os.listdir(images_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".gif"))
        ])

        for img_file in image_files:
            img_path = os.path.join(images_dir, img_file)
            ext = img_file.rsplit(".", 1)[-1] if "." in img_file else "png"

            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            payload = {
                "image_b64": img_b64,
                "image_ext": ext,
                "image_name": img_file,
            }

            call_start = time.time()
            try:
                client = get_lambda_client()
                resp = client.invoke(
                    FunctionName=LAMBDA_FUNCTION_NAME,
                    InvocationType="RequestResponse",
                    Payload=json.dumps(payload),
                )
                resp_payload = json.loads(resp["Payload"].read().decode("utf-8"))

                # Parse the body (Lambda returns statusCode + body)
                if isinstance(resp_payload.get("body"), str):
                    body = json.loads(resp_payload["body"])
                else:
                    body = resp_payload

                call_elapsed = round((time.time() - call_start) * 1000, 2)

                lambda_results.append({
                    "image_name": img_file,
                    "text": body.get("text", ""),
                    "lambda_internal_ms": body.get("elapsed_ms", 0),
                    "roundtrip_ms": call_elapsed,
                })
            except Exception as e:
                call_elapsed = round((time.time() - call_start) * 1000, 2)
                lambda_errors.append({"image_name": img_file, "error": str(e)})
                lambda_results.append({
                    "image_name": img_file,
                    "text": "",
                    "lambda_internal_ms": 0,
                    "roundtrip_ms": call_elapsed,
                    "error": str(e),
                })

    lambda_total_ms = round((time.time() - lambda_total_start) * 1000, 2)

    results["lambdaPerImage"] = {
        "images": lambda_results,
        "totalMs": lambda_total_ms,
        "imageCount": len(lambda_results),
        "errors": lambda_errors,
    }

    # ────────────────────────────────────────
    #  Strategy 2: Direct Tesseract on PDF pages
    # ────────────────────────────────────────
    direct_results = []
    direct_total_start = time.time()

    try:
        doc = fitz.open(pdf_path)

        for page_num in range(doc.page_count):
            page = doc[page_num]

            page_start = time.time()

            # Render page to image at 300 DPI for OCR quality
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")

            pil_img = PILImage.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(pil_img, lang="eng")

            page_elapsed = round((time.time() - page_start) * 1000, 2)

            direct_results.append({
                "page": page_num + 1,
                "text": text.strip(),
                "elapsed_ms": page_elapsed,
            })

        doc.close()
    except Exception as e:
        app.logger.error("Direct OCR failed: %s", e)
        direct_results.append({"page": 0, "text": "", "elapsed_ms": 0, "error": str(e)})

    direct_total_ms = round((time.time() - direct_total_start) * 1000, 2)

    results["directOcr"] = {
        "pages": direct_results,
        "totalMs": direct_total_ms,
        "pageCount": len(direct_results),
    }

    # ── Summary ──
    results["summary"] = {
        "lambdaTotalMs": lambda_total_ms,
        "directOcrTotalMs": direct_total_ms,
        "lambdaImageCount": len(lambda_results),
        "directPageCount": len(direct_results),
        "faster": "lambda" if lambda_total_ms < direct_total_ms else "direct",
        "differenceMs": round(abs(lambda_total_ms - direct_total_ms), 2),
    }

    return jsonify(results)


@app.route("/api/images/<job_id>/<filename>", methods=["GET"])
def serve_image(job_id, filename):
    """Serve an extracted image."""
    safe_job = secure_filename(job_id)
    safe_file = secure_filename(filename)
    images_dir = os.path.join(EXTRACT_DIR, safe_job, "images")

    if not os.path.isfile(os.path.join(images_dir, safe_file)):
        return jsonify({"error": "Image not found"}), 404

    return send_from_directory(images_dir, safe_file)


@app.route("/api/images/<job_id>/download-all", methods=["GET"])
def download_all_images(job_id):
    """Download all extracted images as a zip."""
    safe_job = secure_filename(job_id)
    job_dir = os.path.join(EXTRACT_DIR, safe_job)
    images_dir = os.path.join(job_dir, "images")

    if not os.path.isdir(images_dir):
        return jsonify({"error": "Job not found"}), 404

    zip_path = os.path.join(job_dir, "extracted_images")
    shutil.make_archive(zip_path, "zip", images_dir)

    return send_from_directory(job_dir, "extracted_images.zip",
                               as_attachment=True,
                               download_name="extracted_images.zip")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
