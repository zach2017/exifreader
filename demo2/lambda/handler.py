import os
import json
import time
import base64
import io
import logging
import subprocess
import tempfile
import glob

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Function zip extracts to /var/task in Lambda container.
# We bundle tesseract binaries directly in the zip under bin/ and lib/.
TASK_DIR = os.environ.get("LAMBDA_TASK_ROOT", "/var/task")

TESSERACT = os.path.join(TASK_DIR, "bin", "tesseract")
PDFTOPPM = os.path.join(TASK_DIR, "bin", "pdftoppm")
LIB_DIR = os.path.join(TASK_DIR, "lib")
TESSDATA_DIR = os.path.join(TASK_DIR, "share", "tessdata")

# Set up environment so shared libraries and tessdata are found
os.environ["LD_LIBRARY_PATH"] = LIB_DIR + ":" + os.environ.get("LD_LIBRARY_PATH", "")
os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR


def _cold_start_check():
    for name, path in [("tesseract", TESSERACT), ("pdftoppm", PDFTOPPM)]:
        if os.path.isfile(path):
            logger.info("%s found at %s", name, path)
            os.chmod(path, 0o755)
        else:
            logger.error("%s NOT found at %s", name, path)
    if os.path.isdir(TESSDATA_DIR):
        logger.info("tessdata: %s", str(os.listdir(TESSDATA_DIR)))
    else:
        logger.error("tessdata dir not found: %s", TESSDATA_DIR)
    if os.path.isdir(LIB_DIR):
        logger.info("lib count: %d", len(os.listdir(LIB_DIR)))
    else:
        logger.error("lib dir not found: %s", LIB_DIR)
    # Log TASK_DIR contents for debugging
    if os.path.isdir(TASK_DIR):
        logger.info("TASK_DIR contents: %s", str(os.listdir(TASK_DIR)[:20]))

_cold_start_check()


def handler(event, context):
    t0 = time.perf_counter()
    try:
        file_data = base64.b64decode(event["file_data"])
        file_type = event.get("file_type", "pdf").lower()
        file_name = event.get("file_name", "upload")
        logger.info("Processing %s (%s, %d bytes)", file_name, file_type, len(file_data))

        if file_type == "pdf":
            text, pages = extract_pdf(file_data)
        elif file_type in ("tiff", "tif", "png", "jpg", "jpeg"):
            text = ocr_image_bytes(file_data, file_type)
            pages = 1
        else:
            return make_response(400, error="Unsupported: " + file_type)

        ms = int((time.perf_counter() - t0) * 1000)
        return make_response(200, text=text.strip(), pages=pages, processing_time_ms=ms)

    except Exception as exc:
        logger.exception("Failed")
        ms = int((time.perf_counter() - t0) * 1000)
        return make_response(500, error=str(exc), processing_time_ms=ms)


def extract_pdf(data):
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        pages = len(reader.pages)
        parts = []
        for p in reader.pages:
            t = p.extract_text()
            if t:
                parts.append(t)
        combined = "\n\n".join(parts)
        if len(combined.strip()) > 20:
            return combined, pages
    except Exception as e:
        logger.warning("PyPDF2 failed: %s", str(e))
        pages = 0

    logger.info("Native text empty or failed, using OCR")
    text = ocr_pdf_bytes(data)
    if pages == 0:
        pages = 1
    return text, pages


def ocr_pdf_bytes(data):
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "input.pdf")
        with open(pdf_path, "wb") as f:
            f.write(data)

        img_prefix = os.path.join(tmpdir, "page")
        env = os.environ.copy()
        cmd = [PDFTOPPM, "-r", "300", "-png", pdf_path, img_prefix]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0:
            raise RuntimeError("pdftoppm failed: " + result.stderr[:300])

        pngs = sorted(glob.glob(img_prefix + "*.png"))
        if not pngs:
            raise RuntimeError("pdftoppm produced no images")

        parts = []
        for i, png in enumerate(pngs):
            logger.info("OCR page %d/%d", i + 1, len(pngs))
            text = run_tesseract(png)
            parts.append("--- Page " + str(i + 1) + " ---\n" + text)
        return "\n\n".join(parts)


def ocr_image_bytes(data, ext):
    with tempfile.TemporaryDirectory() as tmpdir:
        img_path = os.path.join(tmpdir, "input." + ext)
        with open(img_path, "wb") as f:
            f.write(data)
        return run_tesseract(img_path)


def run_tesseract(image_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        out_base = os.path.join(tmpdir, "out")
        env = os.environ.copy()
        cmd = [TESSERACT, image_path, out_base, "-l", "eng"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise RuntimeError("tesseract failed: " + result.stderr[:300])
        out_file = out_base + ".txt"
        if os.path.exists(out_file):
            with open(out_file, "r") as f:
                return f.read()
        return ""


def make_response(code, **body):
    return {"statusCode": code, "body": json.dumps(body)}
