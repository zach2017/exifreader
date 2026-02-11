# OCR Lambda Handlers — A Complete Tutorial

This tutorial walks through three AWS Lambda handler files that extract text from images and PDFs. Each handler is explained line-by-line so you can understand exactly what's happening and why.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [handler.py — Image OCR](#handlerpy--image-ocr)
3. [pdf_handler.py — PDF Text Extraction](#pdf_handlerpy--pdf-text-extraction)
4. [pdf_ocr_handler.py — PDF OCR Pipeline](#pdf_ocr_handlerpy--pdf-ocr-pipeline)
5. [How the Three Handlers Relate](#how-the-three-handlers-relate)
6. [Running the Tests](#running-the-tests)

---

## Architecture Overview

These three handlers form a document processing toolkit designed to run on AWS Lambda:

```
┌─────────────────────────────────────────────────────────┐
│                    Client / API Gateway                  │
└────────┬──────────────────┬──────────────────┬──────────┘
         │                  │                  │
         ▼                  ▼                  ▼
   ┌───────────┐    ┌──────────────┐   ┌───────────────┐
   │ handler.py│    │pdf_handler.py│   │pdf_ocr_handler│
   │ Image OCR │    │  PDF Text    │   │   PDF → Image │
   │           │    │  Extraction  │   │    → OCR      │
   │ Tesseract │    │   PyMuPDF    │   │ PyMuPDF +     │
   │           │    │              │   │ Tesseract     │
   └───────────┘    └──────────────┘   └───────────────┘
```

**When to use which:**

- **handler.py** — You have an image (PNG, JPG, TIFF) and want to OCR it into text.
- **pdf_handler.py** — You have a *digital* PDF (text is selectable) and want to extract the embedded text. This is fast because it reads the text layer directly.
- **pdf_ocr_handler.py** — You have a *scanned* PDF (pages are images with no text layer). This renders each page to an image, then OCRs each image. Slower but handles scanned documents.

---

## handler.py — Image OCR

This handler receives a base64-encoded image, writes it to disk, and runs Tesseract OCR on it.

### Imports

```python
import json
import base64
import time
import subprocess
import tempfile
import os
```

- **json** — Parses the incoming event body when routed through API Gateway.
- **base64** — Decodes the base64-encoded image data sent by the client.
- **time** — Tracks how long OCR takes (for performance monitoring).
- **subprocess** — Runs the Tesseract OCR binary as an external process.
- **tempfile** — Creates a temporary file to hold the decoded image (Tesseract reads from disk).
- **os** — Deletes the temp file after processing and extracts file extensions.

### Function: `lambda_handler(event, context)`

This is the entry point AWS Lambda calls.

```python
def lambda_handler(event, context):
```

`event` contains the request data, `context` provides Lambda runtime information (memory limit, remaining time, etc.). We don't use `context` here.

#### Parsing the Input

```python
if "body" in event and "httpMethod" in event:
    body = event.get("body", "")
    if event.get("isBase64Encoded", False):
        body = base64.b64decode(body).decode("utf-8")
    payload = json.loads(body) if isinstance(body, str) else body
else:
    payload = event
```

This block handles **two invocation styles**:

1. **API Gateway proxy format** — When called via HTTP through API Gateway, the event wraps the actual data inside a `body` field (as a JSON string), and includes `httpMethod`. The body itself might be base64-encoded (API Gateway does this for binary payloads).
2. **Direct invocation** — When another Lambda or a test calls this directly, the event IS the payload.

This dual-format support is a common Lambda pattern so the same function works behind an API and in direct testing.

#### Extracting Image Data

```python
image_data = payload.get("image", "")
filename = payload.get("filename", "unknown")

if not image_data:
    return {"error": "No image data provided"}
```

Pulls the base64 image string and an optional filename from the payload. Returns an error dict immediately if no image was sent — this is a common Lambda error response pattern (no HTTP status codes since we're returning a dict).

#### Stripping Data URL Prefix

```python
if "," in image_data:
    image_data = image_data.split(",", 1)[1]
```

Browsers often encode files as data URLs like `data:image/png;base64,iVBORw0KGgo...`. This strips the `data:image/png;base64,` prefix, keeping only the actual base64 content. The `split(",", 1)` ensures we only split on the first comma (the base64 data itself may not contain commas, but this is defensive).

#### Decoding and Writing to Disk

```python
image_bytes = base64.b64decode(image_data)

suffix = os.path.splitext(filename)[1] or ".png"
with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
    tmp.write(image_bytes)
    tmp_path = tmp.name
```

- Decodes the base64 string into raw bytes.
- Extracts the file extension from the filename (e.g., `.jpg` from `photo.jpg`), falling back to `.png`.
- Creates a temporary file with that extension. `delete=False` is crucial — without it, the file would be deleted when the `with` block exits, but Tesseract needs to read it after.
- Saves the file path for Tesseract.

#### Running Tesseract

```python
start_time = time.time()

result = subprocess.run(
    ["tesseract", tmp_path, "stdout", "--oem", "1", "--psm", "3"],
    capture_output=True,
    text=True,
    timeout=30
)

elapsed_ms = round((time.time() - start_time) * 1000, 2)
```

This is the core OCR step. Breaking down the Tesseract command:

- `tesseract` — The Tesseract binary.
- `tmp_path` — Input image file.
- `stdout` — Special keyword telling Tesseract to write output to stdout instead of a file.
- `--oem 1` — OCR Engine Mode 1 = LSTM neural network only (most accurate).
- `--psm 3` — Page Segmentation Mode 3 = "Fully automatic page segmentation but no OSD" (good default for most documents).

The `subprocess.run` parameters:

- `capture_output=True` — Captures both stdout (the extracted text) and stderr (errors/warnings).
- `text=True` — Returns strings instead of bytes.
- `timeout=30` — Kills the process after 30 seconds to prevent Lambda timeouts.

#### Cleanup and Response

```python
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
```

- Deletes the temp file immediately (Lambda has limited `/tmp` space).
- Only reports an error if Tesseract failed AND produced no text. Sometimes Tesseract returns a non-zero exit code but still extracts partial text — that's still useful.
- Returns a rich response with the text, timing data, and basic stats.

---

## pdf_handler.py — PDF Text Extraction

This handler extracts *embedded* text from PDFs using PyMuPDF. It doesn't do OCR — it reads the text layer that digital PDFs already contain.

### Imports

```python
import base64
import os
import tempfile
import time

import fitz  # PyMuPDF
```

`fitz` is the Python binding for MuPDF, a lightweight PDF/XPS viewer library. The import name `fitz` is a historical artifact — it's actually PyMuPDF.

### Function: `pdf_handler(event, context)`

```python
def pdf_handler(event, context):
```

Note this is `pdf_handler`, not `lambda_handler`. AWS Lambda lets you configure which function to call, so each handler can use a descriptive name.

#### Input Parsing

```python
payload = event
pdf_data = payload.get("pdf", "")
filename = payload.get("filename", "unknown.pdf")
```

Unlike `handler.py`, this doesn't handle the API Gateway proxy format — it assumes direct invocation. The payload key is `"pdf"` instead of `"image"`.

#### Writing and Opening the PDF

```python
pdf_bytes = base64.b64decode(pdf_data)

with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp.write(pdf_bytes)
    tmp_path = tmp.name

doc = fitz.open(tmp_path)
page_count = len(doc)
```

Same temp-file pattern as before. `fitz.open()` loads the PDF and `len(doc)` gives the page count. PyMuPDF needs a file path (or bytes buffer), hence the temp file.

#### Per-Page Text Extraction

```python
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
```

- `page.get_text("text")` extracts plain text from the page. The `"text"` argument specifies the output format (other options include `"html"`, `"dict"`, `"blocks"`).
- Each page is timed individually — useful for identifying pages with complex layouts that take longer.
- Statistics (word count, char count) are tracked per-page and totalled.
- `full_text_parts` collects all page texts to join later.

#### Building the Response

```python
doc.close()
total_ms = round((time.time() - total_start) * 1000, 2)
os.unlink(tmp_path)

full_text = "\n\n".join(full_text_parts)
```

- Closes the document to free memory.
- Joins all page texts with double newlines for clear page separation.

The return dict includes everything: the combined text, per-page breakdowns, file size, and timing.

---

## pdf_ocr_handler.py — PDF OCR Pipeline

This is the most complex handler. It combines both previous approaches: PyMuPDF renders PDF pages to images, then Tesseract OCRs each image.

### Pipeline Flow

```
PDF bytes → temp file → PyMuPDF opens
    → For each page:
        → Render to PNG image (PyMuPDF)
        → Write PNG to temp file
        → Run Tesseract on PNG
        → Collect text
    → Join all page texts
    → Return with detailed timing
```

### Helper: `run_tesseract(image_path)`

```python
def run_tesseract(image_path: str) -> tuple[str, float]:
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
```

Extracted as a separate function for clarity and testability. Same Tesseract invocation as `handler.py` but with a 60-second timeout (PDF pages rendered at high DPI can be large). Unlike the main handler, this **raises an exception** on failure instead of returning an error dict — the calling function catches it.

### Helper: `extract_page_image(page, dpi)`

```python
def extract_page_image(page, dpi: int = 300) -> tuple[bytes, float]:
    start = time.time()
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    elapsed_ms = round((time.time() - start) * 1000, 2)
    return png_bytes, elapsed_ms
```

- `fitz.Matrix(dpi / 72, dpi / 72)` creates a scaling matrix. PDFs use 72 points per inch internally, so dividing the target DPI by 72 gives the scale factor. At 300 DPI, each point becomes ~4.17 pixels.
- `page.get_pixmap(matrix=mat)` renders the page to a pixel buffer at the specified resolution.
- `pix.tobytes("png")` encodes the pixel buffer as a PNG image in memory.
- Higher DPI means better OCR accuracy but larger images and slower processing. 300 DPI is a solid default for OCR.

### Main Function: `pdf_ocr_handler(event, context)`

#### The Page Loop

```python
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
```

For each page:

1. Render to PNG — timed separately as `extract_ms`.
2. Write the PNG to a temp file (Tesseract reads from disk).
3. Run OCR — timed separately as `ocr_ms`.
4. Delete the temp image immediately to conserve `/tmp` space.

This creates and deletes a temp file per page. On a 100-page PDF, that's 100 temp files created and destroyed sequentially. The alternative (keeping all in memory) would use too much RAM on Lambda.

#### Timing Breakdown

```python
"timing": {
    "pipeline_ms": pipeline_ms,
    "total_image_extract_ms": round(total_extract_ms, 2),
    "total_ocr_ms": round(total_ocr_ms, 2),
    "avg_extract_per_page_ms": round(total_extract_ms / max(page_count, 1), 2),
    "avg_ocr_per_page_ms": round(total_ocr_ms / max(page_count, 1), 2),
},
```

The response includes a detailed timing breakdown so you can identify bottlenecks:

- `pipeline_ms` — Wall-clock time for the entire operation.
- `total_image_extract_ms` — Total time spent rendering pages to images.
- `total_ocr_ms` — Total time spent in Tesseract.
- Averages per page help predict processing time for larger documents.

The `max(page_count, 1)` prevents division by zero if somehow a zero-page document gets through.

---

## How the Three Handlers Relate

| Feature | handler.py | pdf_handler.py | pdf_ocr_handler.py |
|---|---|---|---|
| **Input** | Base64 image | Base64 PDF | Base64 PDF |
| **Method** | Tesseract OCR | PyMuPDF text extraction | PyMuPDF render + Tesseract |
| **Use case** | Photos, scanned images | Digital PDFs | Scanned PDFs |
| **Speed** | Fast (single image) | Very fast (no OCR) | Slow (render + OCR per page) |
| **Dependencies** | Tesseract | PyMuPDF | Both |
| **API Gateway** | Yes | No | No |

A common deployment pattern is to have a router Lambda that inspects the file type and invokes the appropriate handler.

---

## Running the Tests

### Prerequisites

```bash
pip install pytest pymupdf
```

Tesseract is **not** needed for tests — all external calls are mocked.

### Running All Tests

```bash
pytest -v
```

### Running Tests for a Single Handler

```bash
pytest test_handler.py -v           # Image OCR tests
pytest test_pdf_handler.py -v       # PDF text extraction tests
pytest test_pdf_ocr_handler.py -v   # PDF OCR pipeline tests
```

### Test Structure

Each test file follows the same organization:

- **Success tests** — Happy path: valid input produces expected output.
- **Error tests** — Missing data, invalid base64, tool failures.
- **Edge case tests** — Empty text, default values, partial failures.

All tests use `unittest.mock` to patch external dependencies (Tesseract subprocess calls, PyMuPDF file operations, temp file creation). This makes the tests fast, deterministic, and runnable without any system dependencies.
