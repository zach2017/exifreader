# OCR Extract — Complete Developer Tutorial

> **A hands-on guide to building a Dockerized OCR service with image and PDF text extraction, reverse proxy routing, and a polished browser UI.**

---

## Table of Contents

1. [What Are We Building?](#1-what-are-we-building)
2. [Architecture & Data Flow](#2-architecture--data-flow)
3. [Dependency Map](#3-dependency-map)
4. [Project Structure](#4-project-structure)
5. [File-by-File Walkthrough](#5-file-by-file-walkthrough)
   - 5.1 [docker-compose.yml — Orchestration](#51-docker-composeyml--orchestration)
   - 5.2 [lambda/Dockerfile — Building the OCR Container](#52-lambdadockerfile--building-the-ocr-container)
   - 5.3 [lambda/server.py — The Lambda-Compatible Router](#53-lambdaserverpy--the-lambda-compatible-router)
   - 5.4 [lambda/handler.py — Image OCR Handler](#54-lambdahandlerpy--image-ocr-handler)
   - 5.5 [lambda/pdf_handler.py — Direct PDF Text Extraction](#55-lambdapdf_handlerpy--direct-pdf-text-extraction)
   - 5.6 [lambda/pdf_ocr_handler.py — PDF→Image→OCR Pipeline](#56-lambdapdf_ocr_handlerpy--pdfimagocr-pipeline)
   - 5.7 [nginx/default.conf — Reverse Proxy Configuration](#57-nginxdefaultconf--reverse-proxy-configuration)
   - 5.8 [app/index.html — Frontend Application](#58-appindexhtml--frontend-application)
   - 5.9 [ocr_client.py — CLI Client](#59-ocr_clientpy--cli-client)
6. [Data Flow Diagrams](#6-data-flow-diagrams)
7. [How to Run](#7-how-to-run)
8. [Glossary](#8-glossary)

---

## 1. What Are We Building?

This project is a **self-contained OCR (Optical Character Recognition) service** that runs entirely inside [Docker](https://docs.docker.com/get-started/overview/) containers. You upload an image or PDF through a web browser (or a command-line tool), and the system extracts every word of text from it.

There are **three extraction services** bundled into one container, each color-coded in the UI:

| Service | Color | What It Does | When To Use |
|---------|-------|-------------|-------------|
| **Image OCR** | 🟢 Green | Runs Tesseract directly on an uploaded image | Screenshots, photos of documents, scanned images |
| **PDF Text Extract** | 🔵 Blue | Pulls embedded text from a PDF using PyMuPDF — **no OCR** | Digitally-created PDFs (Word exports, web saves). Fastest option. |
| **PDF→Image→OCR** | 🩷 Pink | Renders each PDF page as an image, then OCRs it | Scanned PDFs, image-only PDFs, PDFs where direct text extraction returns nothing |

**When to use which PDF service?** Try **PDF Text** first — it's 100x faster because it reads embedded text directly without rendering images or running OCR. If it returns no text (common with scanned documents), switch to **PDF OCR**, which renders each page as a 300 DPI image and runs Tesseract on it.

---

## 2. Architecture & Data Flow

### System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                         HOST MACHINE                           │
│                                                                │
│  ┌──────────────┐         ┌──────────────────────────────────┐ │
│  │   Browser     │────────▶│  Nginx Container  :8080          │ │
│  │   (or CLI)    │◀────────│                                  │ │
│  └──────────────┘         │  GET  /            → index.html   │ │
│                           │  POST /api/ocr     ─┐             │ │
│                           │  POST /api/pdf     ─┤ proxy_pass  │ │
│                           │  POST /api/pdf-ocr ─┘             │ │
│                           └──────────┬───────────────────────┘ │
│                                      │                         │
│                                      ▼                         │
│                           ┌──────────────────────────────────┐ │
│                           │  Lambda Container  :9000          │ │
│                           │                                   │ │
│                           │  Flask server.py routes to:       │ │
│                           │    ├── handler.py      (images)   │ │
│                           │    ├── pdf_handler.py  (PDF text) │ │
│                           │    └── pdf_ocr_handler.py         │ │
│                           │         (PDF → Image → Tesseract) │ │
│                           │                                   │ │
│                           │  System packages:                 │ │
│                           │    ├── tesseract-ocr              │ │
│                           │    ├── poppler-utils              │ │
│                           │    └── pymupdf (fitz)             │ │
│                           └──────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### Request Lifecycle: PDF Text Extract (no OCR)

```
1. User drops PDF onto browser (PDF Text tab)
2. JavaScript FileReader converts file → base64 data URL
3. fetch() POSTs JSON { pdf: "data:application/pdf;base64,JVBERi...", filename: "doc.pdf" }
         │
         ▼
4. Nginx receives POST /api/pdf
5. proxy_pass rewrites to http://lambda:9000/2015-03-31/functions/pdf-extract/invocations
         │
         ▼
6. Flask server.py receives request, looks up "pdf-extract" in HANDLERS dict
7. Calls pdf_handler.pdf_handler(event, None)
         │
         ▼
8. pdf_handler.py:
   a. Strips "data:application/pdf;base64," prefix → pure base64
   b. base64.b64decode() → raw PDF bytes
   c. Writes bytes to /tmp/tmpXXXXXX.pdf
   d. fitz.open(pdf_path)
   e. FOR EACH PAGE:
      - page.get_text("text") → reads embedded text directly
      - ⏱ measures extraction_time_ms per page
   f. doc.close(), delete temp file
   g. Returns JSON { text, processing_time_ms, page_count, pages[...] }
         │
         ▼
9. Flask jsonify() sends response back through Nginx to browser
10. JavaScript renders text + per-page timing table
```

### Request Lifecycle (Image OCR)

```
1. User drops image onto browser
2. JavaScript FileReader converts file → base64 data URL
3. fetch() POSTs JSON { image: "data:image/png;base64,iVBOR...", filename: "scan.png" }
         │
         ▼
4. Nginx receives POST /api/ocr
5. proxy_pass rewrites to http://lambda:9000/2015-03-31/functions/ocr-service/invocations
         │
         ▼
6. Flask server.py receives request, looks up "ocr-service" in HANDLERS dict
7. Calls handler.lambda_handler(event, None)
         │
         ▼
8. handler.py:
   a. Strips "data:image/png;base64," prefix → pure base64
   b. base64.b64decode() → raw image bytes
   c. Writes bytes to /tmp/tmpXXXXXX.png
   d. subprocess.run(["tesseract", "/tmp/tmpXXXXXX.png", "stdout", ...])
   e. Captures stdout (extracted text), measures elapsed time
   f. Deletes temp file
   g. Returns JSON { text, processing_time_ms, word_count, ... }
         │
         ▼
9. Flask jsonify() sends response back through Nginx to browser
10. JavaScript renders text + stats in the results card
```

### Request Lifecycle (PDF→Image→OCR Pipeline)

```
1. User drops PDF onto browser
2. JavaScript FileReader converts file → base64 data URL
3. fetch() POSTs JSON { pdf: "data:application/pdf;base64,JVBERi...", filename: "doc.pdf" }
         │
         ▼
4. Nginx receives POST /api/pdf-ocr
5. proxy_pass rewrites to http://lambda:9000/2015-03-31/functions/pdf-ocr/invocations
         │
         ▼
6. Flask routes to pdf_ocr_handler()
         │
         ▼
7. pdf_ocr_handler.py — FOR EACH PAGE:
   ┌──────────────────────────────────────────────────────────────┐
   │  Step A: PyMuPDF renders page as 300 DPI PNG                 │
   │          page.get_pixmap(matrix=Matrix(300/72, 300/72))      │
   │          → png_bytes (≈65KB per page)                        │
   │          ⏱ image_extract_ms                                  │
   │                        │                                     │
   │                        ▼                                     │
   │  Step B: Write PNG to /tmp/tmpXXXXXX.png                     │
   │                        │                                     │
   │                        ▼                                     │
   │  Step C: subprocess.run(["tesseract", tmp.png, "stdout"])    │
   │          → extracted text from this page                     │
   │          ⏱ ocr_ms                                            │
   │                        │                                     │
   │                        ▼                                     │
   │  Step D: Delete temp PNG, collect page results               │
   └──────────────────────────────────────────────────────────────┘
         │
         ▼
8. Combine all page texts with "\n\n" separator
9. Return JSON with text + per-page timing + aggregate stats
```

---

## 3. Dependency Map

Every tool and library in this project serves a specific purpose. Here is every dependency, why it exists, and where to find its documentation.

### System-Level Dependencies (installed via apt-get)

| Package | Purpose | Why We Need It | Official Docs |
|---------|---------|---------------|---------------|
| **python:3.11-slim-bookworm** | Base Docker image. Debian 12 "Bookworm" with Python 3.11 pre-installed. "slim" variant excludes dev tools to minimize image size (~150MB vs ~900MB full). | Provides the Python runtime and working apt repos (critical — older Debian versions like Buster have dead repos). | [Docker Hub: python](https://hub.docker.com/_/python) · [Python 3.11 Docs](https://docs.python.org/3.11/) |
| **tesseract-ocr** | Google's open-source OCR engine. Converts images of text into machine-readable strings. | The core OCR engine — without it, we cannot extract text from images. | [Tesseract GitHub](https://github.com/tesseract-ocr/tesseract) · [Tesseract Docs](https://tesseract-ocr.github.io/) |
| **tesseract-ocr-eng** | English language trained data for Tesseract. Contains neural network models for recognizing English characters. | Tesseract needs at least one language pack. Without this, it cannot recognize any text. Other languages available: `tesseract-ocr-fra`, `tesseract-ocr-deu`, etc. | [Tessdata Repository](https://github.com/tesseract-ocr/tessdata) |
| **poppler-utils** | PDF rendering utilities including `pdftotext`, `pdftoppm`, `pdfinfo`. | Provides the `pdftotext` command-line tool for direct PDF text extraction. While we primarily use PyMuPDF programmatically, poppler is a well-tested fallback. | [Poppler](https://poppler.freedesktop.org/) · [Poppler GitLab](https://gitlab.freedesktop.org/poppler/poppler) |
| **curl** | Command-line HTTP client. | Used inside the container's healthcheck to verify the Flask server is running (`curl -f http://localhost:9000/health`). Docker needs this to know when the service is ready. | [curl Docs](https://curl.se/docs/) |
| **nginx:alpine** | Lightweight web server and reverse proxy. Alpine Linux base (~5MB). | Serves the static HTML/CSS/JS frontend and proxies API requests to the Lambda container. Keeps the frontend and backend decoupled. | [Nginx Docs](https://nginx.org/en/docs/) · [Docker Hub: nginx](https://hub.docker.com/_/nginx) |

### Python Dependencies (installed via pip)

| Package | Import Name | Purpose | Why We Need It | Official Docs |
|---------|-------------|---------|---------------|---------------|
| **Flask** | `flask` | Lightweight WSGI web framework. | Runs the HTTP server that receives Lambda invoke requests. Chosen for simplicity — just 1 file, ~40 lines. No need for Django or FastAPI here. | [Flask Docs](https://flask.palletsprojects.com/) · [PyPI](https://pypi.org/project/Flask/) |
| **PyMuPDF** | `fitz` | Python bindings for MuPDF, a high-performance PDF/XPS renderer. | Two critical jobs: (1) extract embedded text from PDFs directly, (2) render PDF pages as high-resolution PNG images for the OCR pipeline. It's significantly faster than alternatives like `pdf2image` + Ghostscript. | [PyMuPDF Docs](https://pymupdf.readthedocs.io/) · [PyPI](https://pypi.org/project/PyMuPDF/) · [GitHub](https://github.com/pymupdf/PyMuPDF) |

> **Why `import fitz`?** PyMuPDF's import name is `fitz` because it was originally based on the Fitz graphics library, which is the rendering engine inside MuPDF. The package name on PyPI is `PyMuPDF`, but you always import it as `fitz`.

### Frontend Dependencies (loaded via CDN)

| Library | Purpose | Why We Need It | Official Docs |
|---------|---------|---------------|---------------|
| **Tailwind CSS** (CDN) | Utility-first CSS framework. Every style is a class like `text-white`, `rounded-xl`, `bg-surface-800`. | Rapid UI development without writing custom CSS files. The CDN version (`cdn.tailwindcss.com`) includes a JIT compiler that generates styles on-the-fly in the browser. | [Tailwind CSS Docs](https://tailwindcss.com/docs) · [CDN Play](https://tailwindcss.com/docs/installation/play-cdn) |
| **Google Fonts** | Loads `Outfit` (display) and `JetBrains Mono` (monospace) typefaces. | `Outfit` provides a clean, modern UI font. `JetBrains Mono` is designed specifically for code and data readability. | [Google Fonts](https://fonts.google.com/) · [Outfit](https://fonts.google.com/specimen/Outfit) · [JetBrains Mono](https://fonts.google.com/specimen/JetBrains+Mono) |

### CLI Client Dependencies

| Package | Purpose | Official Docs |
|---------|---------|---------------|
| **requests** | HTTP library for Python. Simpler API than `urllib3`. | [Requests Docs](https://requests.readthedocs.io/) · [PyPI](https://pypi.org/project/requests/) |

### Docker & Orchestration

| Tool | Purpose | Official Docs |
|------|---------|---------------|
| **Docker** | Containerization platform. Packages each service with its dependencies into isolated, reproducible environments. | [Docker Docs](https://docs.docker.com/) · [Install Docker](https://docs.docker.com/get-docker/) |
| **Docker Compose** | Multi-container orchestration. Defines and runs both containers (nginx + lambda) from a single YAML file. | [Compose Docs](https://docs.docker.com/compose/) · [Compose File Ref](https://docs.docker.com/compose/compose-file/) |

---

## 4. Project Structure

```
ocr-app/
│
├── docker-compose.yml          # Orchestrates both containers
│
├── app/
│   └── index.html              # Frontend: HTML + Tailwind CSS + JavaScript (462 lines)
│
├── nginx/
│   └── default.conf            # Nginx: static files + reverse proxy rules
│
├── lambda/
│   ├── Dockerfile              # Builds Python + Tesseract + PyMuPDF image
│   ├── server.py               # Flask router (Lambda invoke API emulation)
│   ├── handler.py              # Service 1: Image → Tesseract → Text
│   ├── pdf_handler.py          # Service 2: PDF → Direct text extraction
│   └── pdf_ocr_handler.py      # Service 3: PDF → Render images → Tesseract → Text
│
├── ocr_client.py               # CLI tool: send files, get CSV output
└── README.md
```

---

## 5. File-by-File Walkthrough

### 5.1 `docker-compose.yml` — Orchestration

This file tells Docker Compose how to build, connect, and run both containers.

**Reference:** [Compose File Specification](https://docs.docker.com/compose/compose-file/)

```yaml
version: "3.8"
```

**Line 1:** Declares the [Compose file format version](https://docs.docker.com/compose/compose-file/compose-versioning/). Version `3.8` supports all features we need: healthchecks, `depends_on` conditions, and build contexts. While newer versions of Docker Compose ignore this field, it ensures backward compatibility.

```yaml
services:
  # ── Web Server (static HTML + reverse proxy) ──
  web:
    image: nginx:alpine
```

**Lines 3–6:** Defines the first service, named `web`. Instead of building from a Dockerfile, it pulls the official [`nginx:alpine`](https://hub.docker.com/_/nginx) image directly. Alpine Linux is a minimal distribution (~5MB) — the full Nginx image based on Debian would be ~140MB.

```yaml
    ports:
      - "8080:80"
```

**Lines 7–8:** [Port mapping](https://docs.docker.com/compose/networking/#ports). Maps host port `8080` to container port `80`. The syntax is `HOST:CONTAINER`. Nginx listens on port 80 inside the container (its default), and we expose it as `8080` on your machine so you access the app at `http://localhost:8080`.

```yaml
    volumes:
      - ./app:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
```

**Lines 9–11:** [Bind mounts](https://docs.docker.com/storage/bind-mounts/). These map files from your host filesystem into the container:

- **`./app` → `/usr/share/nginx/html`**: Nginx's default document root. Our `index.html` becomes the served webpage.
- **`./nginx/default.conf` → `/etc/nginx/conf.d/default.conf`**: Replaces Nginx's default server configuration with our custom one (which includes the reverse proxy rules).
- **`:ro`** means read-only — the container can read these files but cannot modify them.

```yaml
    depends_on:
      lambda:
        condition: service_healthy
```

**Lines 12–14:** [Startup ordering with health conditions](https://docs.docker.com/compose/startup-order/). Docker Compose will not start the `web` container until the `lambda` container reports healthy. Without this, Nginx would start proxying requests to a service that isn't ready yet, resulting in `502 Bad Gateway` errors.

```yaml
    restart: unless-stopped
```

**Line 15:** [Restart policy](https://docs.docker.com/compose/compose-file/05-services/#restart). If the container crashes, Docker automatically restarts it. The `unless-stopped` policy means it restarts on failure but not if you manually stop it with `docker compose stop`.

```yaml
  # ── Lambda OCR Service (Tesseract + Lambda-compatible invoke endpoint) ──
  lambda:
    build:
      context: ./lambda
      dockerfile: Dockerfile
```

**Lines 18–21:** The second service, named `lambda`. Unlike `web`, this one is [built from a Dockerfile](https://docs.docker.com/compose/compose-file/build/). The `context` tells Docker where to find the build files — everything in `./lambda/` becomes available during the build.

```yaml
    ports:
      - "9000:9000"
```

**Lines 22–23:** Exposes port `9000` for direct access. This is optional (Nginx proxies to it internally via Docker's network), but useful for debugging and the CLI's `--direct` flag.

```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/health"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 5s
```

**Lines 24–29:** [Container healthcheck](https://docs.docker.com/compose/compose-file/05-services/#healthcheck). Docker periodically runs this command inside the container:

- **`curl -f`**: The `-f` flag makes curl return a non-zero exit code on HTTP errors (4xx, 5xx).
- **`interval: 5s`**: Check every 5 seconds.
- **`timeout: 5s`**: If a check takes longer than 5 seconds, count it as failed.
- **`retries: 5`**: After 5 consecutive failures, mark the container as `unhealthy`.
- **`start_period: 5s`**: Give the container 5 seconds of grace time before health checks start counting failures. This allows Flask time to initialize.

The `web` service's `depends_on: condition: service_healthy` waits for this healthcheck to pass.

```yaml
    restart: unless-stopped
```

**Line 30:** Same restart policy as the web service.

---

### 5.2 `lambda/Dockerfile` — Building the OCR Container

This Dockerfile creates a Docker image containing Python, Tesseract OCR, PDF tools, and our application code.

**Reference:** [Dockerfile Reference](https://docs.docker.com/reference/dockerfile/)

```dockerfile
FROM python:3.11-slim-bookworm
```

**Line 1:** [Base image](https://docs.docker.com/reference/dockerfile/#from). Starts from the official Python 3.11 image built on Debian 12 "Bookworm".

Why these specific choices?

- **Python 3.11** — Supports modern syntax like `tuple[str, float]` type hints used in `pdf_ocr_handler.py`.
- **`slim`** — Excludes C compilers, dev headers, and documentation. Reduces image size from ~900MB to ~150MB. PyMuPDF ships pre-compiled wheels, so we don't need build tools.
- **`bookworm`** — Debian 12 (current stable). Critical: earlier versions like Buster (Debian 10) have end-of-life apt repositories that no longer resolve, causing `apt-get update` to fail.

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
```

**Lines 4–10:** [RUN instruction](https://docs.docker.com/reference/dockerfile/#run) — executes shell commands during image build. This single `RUN` chains multiple commands with `&&` to create a single Docker layer (each `RUN` creates a layer; fewer layers = smaller image).

Step by step:

1. **`apt-get update`** — Refreshes the package index from Debian's repositories.
2. **`apt-get install -y --no-install-recommends`** — Installs packages without recommended (but non-essential) extras. `-y` auto-confirms.
3. **`tesseract-ocr`** — The OCR engine binary (v5.x on Bookworm).
4. **`tesseract-ocr-eng`** — English trained data files (~4MB of neural network models).
5. **`poppler-utils`** — PDF command-line utilities.
6. **`curl`** — Required by the healthcheck command.
7. **`apt-get clean && rm -rf /var/lib/apt/lists/*`** — Removes cached package files to shrink the final image. This is a [Docker best practice](https://docs.docker.com/build/building/best-practices/#apt-get).

```dockerfile
RUN tesseract --version && which tesseract
```

**Line 13:** A build-time verification step. If Tesseract wasn't installed correctly, this command fails and the entire Docker build aborts. This is a "fail fast" pattern — catch problems during build, not at runtime.

```dockerfile
RUN pip install --no-cache-dir flask pymupdf
```

**Line 16:** Installs Python packages. `--no-cache-dir` prevents pip from storing downloaded wheels in a cache directory, keeping the image smaller.

- **`flask`** — Web framework for the HTTP server.
- **`pymupdf`** — PDF rendering library (imports as `fitz`).

```dockerfile
WORKDIR /app
COPY handler.py .
COPY pdf_handler.py .
COPY pdf_ocr_handler.py .
COPY server.py .
```

**Lines 18–22:** [WORKDIR](https://docs.docker.com/reference/dockerfile/#workdir) sets the working directory to `/app`. All subsequent `COPY` commands place files there. [COPY](https://docs.docker.com/reference/dockerfile/#copy) transfers files from the build context (the `./lambda/` directory) into the image.

We copy each file individually rather than using `COPY . .` to take advantage of Docker's [layer caching](https://docs.docker.com/build/cache/). If only `server.py` changes, Docker reuses cached layers for the other files.

```dockerfile
EXPOSE 9000
```

**Line 24:** [EXPOSE](https://docs.docker.com/reference/dockerfile/#expose) documents that the container listens on port 9000. This is informational — it doesn't actually open the port. The `ports:` directive in `docker-compose.yml` does the actual mapping.

```dockerfile
CMD ["python", "server.py"]
```

**Line 26:** [CMD](https://docs.docker.com/reference/dockerfile/#cmd) defines the command that runs when the container starts. The exec form `["python", "server.py"]` runs Python directly (no shell wrapper), which ensures signals like SIGTERM are delivered correctly for graceful shutdown.

---

### 5.3 `lambda/server.py` — The Lambda-Compatible Router

This is the HTTP entry point inside the Lambda container. It's a thin Flask application that mimics the [AWS Lambda Invoke API](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html) endpoint format.

**Why mimic the Lambda API?** The URL pattern `/2015-03-31/functions/{name}/invocations` is the real endpoint that AWS (and tools like [LocalStack](https://docs.localstack.cloud/user-guide/aws/lambda/)) use. By using the same pattern, this code is portable — if you later deploy to real AWS Lambda, the frontend and Nginx config don't need to change.

```python
"""
Lambda-compatible invoke server.
Routes:
  POST /2015-03-31/functions/ocr-service/invocations    → Image OCR (Tesseract)
  POST /2015-03-31/functions/pdf-extract/invocations     → PDF direct text extraction
  POST /2015-03-31/functions/pdf-ocr/invocations         → PDF → Image → OCR pipeline
"""
```

**Lines 1–7:** Module docstring. Documents all three routes the server handles.

```python
from flask import Flask, request, jsonify
from handler import lambda_handler
from pdf_handler import pdf_handler
from pdf_ocr_handler import pdf_ocr_handler
```

**Lines 9–12:** Imports.

- **`Flask`** — [Application factory](https://flask.palletsprojects.com/en/stable/api/#flask.Flask). Creates the WSGI application.
- **`request`** — [Request context](https://flask.palletsprojects.com/en/stable/api/#flask.request). A thread-local proxy that gives access to the incoming HTTP request's headers, body, method, etc.
- **`jsonify`** — [JSON response helper](https://flask.palletsprojects.com/en/stable/api/#flask.json.jsonify). Converts a Python dictionary to a JSON HTTP response with the correct `Content-Type: application/json` header.
- **Lines 10–12:** Imports the handler functions from our three service modules. Each follows the AWS Lambda handler signature: `handler(event, context)`.

```python
app = Flask(__name__)
```

**Line 14:** Creates a Flask application instance. `__name__` tells Flask the name of the current module, which it uses to locate resources and configure logging.

```python
HANDLERS = {
    "ocr-service": lambda_handler,
    "pdf-extract": pdf_handler,
    "pdf-ocr": pdf_ocr_handler,
}
```

**Lines 16–20:** A routing dictionary. Maps function names (from the URL) to Python handler functions. This pattern is a **strategy pattern** — the URL determines which processing function to invoke, without needing separate route decorators for each.

```python
@app.route("/2015-03-31/functions/<function_name>/invocations", methods=["POST"])
def invoke(function_name):
    """Mimics the Lambda Invoke API — routes to the correct handler."""
    handler = HANDLERS.get(function_name)
    if not handler:
        return jsonify({"error": f"Unknown function: {function_name}"}), 404
    try:
        event = request.get_json(force=True)
        result = handler(event, None)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

**Lines 23–34:** The core route handler. Let's trace it:

- **Line 23:** [`@app.route()`](https://flask.palletsprojects.com/en/stable/api/#flask.Flask.route) decorator registers this function for the given URL pattern. `<function_name>` is a [URL variable](https://flask.palletsprojects.com/en/stable/quickstart/#variable-rules) — Flask extracts whatever string appears in that position and passes it as a parameter. For example, a POST to `/2015-03-31/functions/pdf-ocr/invocations` sets `function_name = "pdf-ocr"`.
- **Line 26:** Looks up the handler in our `HANDLERS` dictionary. If someone requests an unknown function name, return 404.
- **Line 30:** [`request.get_json(force=True)`](https://flask.palletsprojects.com/en/stable/api/#flask.Request.get_json) parses the request body as JSON. `force=True` parses even if the `Content-Type` header isn't exactly `application/json` (a defensive measure).
- **Line 31:** Calls the handler with `(event, None)`. The `event` is the parsed JSON body. `None` stands in for the AWS Lambda [context object](https://docs.aws.amazon.com/lambda/latest/dg/python-context.html), which we don't use.
- **Line 32:** Returns the handler's result as JSON with HTTP 200.
- **Line 34:** Catches any unhandled exception and returns it as a 500 error with the error message.

```python
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "services": list(HANDLERS.keys())}), 200
```

**Lines 37–39:** Health check endpoint. Returns the list of available services. Docker's healthcheck (`curl -f http://localhost:9000/health`) calls this every 5 seconds to confirm the server is alive.

```python
if __name__ == "__main__":
    print("=" * 60)
    print("  Lambda Service running on :9000")
    print("  POST .../functions/ocr-service/invocations   (images)")
    print("  POST .../functions/pdf-extract/invocations    (PDF text)")
    print("  POST .../functions/pdf-ocr/invocations        (PDF→OCR)")
    print("=" * 60)
    app.run(host="0.0.0.0", port=9000)
```

**Lines 42–49:** The entry point. [`if __name__ == "__main__"`](https://docs.python.org/3/library/__main__.html) ensures this code only runs when the file is executed directly (not when imported).

- **`host="0.0.0.0"`** — Listen on all network interfaces. Inside Docker, `localhost` (`127.0.0.1`) won't accept connections from other containers. `0.0.0.0` means "accept from anywhere" — necessary because Nginx connects to this server over Docker's internal bridge network.
- **`port=9000`** — Matches the `EXPOSE` in the Dockerfile and the `ports` in docker-compose.yml.

---

### 5.4 `lambda/handler.py` — Image OCR Handler

This handler receives a base64-encoded image, saves it to a temporary file, runs Tesseract, and returns the extracted text.

```python
import json
import base64
import time
import subprocess
import tempfile
import os
```

**Lines 1–6:** Standard library imports.

| Module | Purpose | Docs |
|--------|---------|------|
| `json` | Parse JSON strings (for API Gateway format support) | [json](https://docs.python.org/3/library/json.html) |
| `base64` | Decode base64-encoded image data from the browser | [base64](https://docs.python.org/3/library/base64.html) |
| `time` | `time.time()` for measuring OCR processing duration | [time](https://docs.python.org/3/library/time.html) |
| `subprocess` | Spawn Tesseract as a child process | [subprocess](https://docs.python.org/3/library/subprocess.html) |
| `tempfile` | Create temporary files safely (auto-generated unique names) | [tempfile](https://docs.python.org/3/library/tempfile.html) |
| `os` | `os.unlink()` to delete temp files, `os.path.splitext()` for extensions | [os](https://docs.python.org/3/library/os.html) |

```python
def lambda_handler(event, context):
    """OCR Lambda handler - extracts text from uploaded images."""
```

**Lines 9–10:** The function signature follows the [AWS Lambda handler convention](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html): `handler(event, context)`. The `event` parameter is the parsed JSON request body. The `context` parameter (unused here, passed as `None`) would normally contain Lambda runtime metadata.

```python
    try:
        # Support both direct invocation and API Gateway proxy format
        if "body" in event and "httpMethod" in event:
            body = event.get("body", "")
            if event.get("isBase64Encoded", False):
                body = base64.b64decode(body).decode("utf-8")
            payload = json.loads(body) if isinstance(body, str) else body
        else:
            payload = event
```

**Lines 12–20:** Input format detection. This handler accepts two formats:

1. **Direct invocation** (our normal case): The `event` IS the payload: `{"image": "...", "filename": "..."}`.
2. **[API Gateway proxy format](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html)**: API Gateway wraps the payload inside `{"body": "...", "httpMethod": "POST", "isBase64Encoded": false}`. This branch unwraps it.

This dual-format support means the same handler code works whether called directly or through AWS API Gateway.

```python
        image_data = payload.get("image", "")
        filename = payload.get("filename", "unknown")

        if not image_data:
            return {"error": "No image data provided"}
```

**Lines 22–26:** Extract the image data and filename from the payload. If no image data was sent, return an error immediately.

```python
        # Strip data URL prefix if present (e.g. "data:image/png;base64,...")
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]
```

**Lines 28–30:** The browser's [`FileReader.readAsDataURL()`](https://developer.mozilla.org/en-US/docs/Web/API/FileReader/readAsDataURL) produces strings like `data:image/png;base64,iVBORw0KGgo...`. The prefix before the comma is a [Data URL](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs) scheme — it tells the browser the MIME type and encoding, but Tesseract doesn't need it. We split on the first comma and keep only the base64 portion.

```python
        image_bytes = base64.b64decode(image_data)
```

**Line 33:** [`base64.b64decode()`](https://docs.python.org/3/library/base64.html#base64.b64decode) converts the base64 string back into raw binary image bytes. Base64 encoding inflates data by ~33% (3 bytes become 4 characters), so this reverses that.

```python
        suffix = os.path.splitext(filename)[1] or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
```

**Lines 36–39:** Write the image bytes to a temporary file.

- **`os.path.splitext("scan.png")`** returns `("scan", ".png")`. We use the original extension so Tesseract knows the image format.
- **[`NamedTemporaryFile`](https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile)** creates a file like `/tmp/tmp8a3f2x1k.png`. `delete=False` keeps the file after the `with` block exits — we need it to persist until Tesseract finishes reading it.

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

**Lines 42–51:** The core OCR operation. Let's break down the [subprocess.run()](https://docs.python.org/3/library/subprocess.html#subprocess.run) call:

**Tesseract command arguments:**

| Argument | Meaning |
|----------|---------|
| `tesseract` | The Tesseract binary |
| `tmp_path` | Input image file path |
| `stdout` | Output destination — `stdout` means "write text to standard output" (instead of a file) |
| `--oem 1` | **OCR Engine Mode 1** = LSTM neural network only (most accurate). [Tesseract OEM modes](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html): 0=legacy, 1=LSTM, 2=legacy+LSTM, 3=auto |
| `--psm 3` | **Page Segmentation Mode 3** = Fully automatic page segmentation (no orientation detection). [Tesseract PSM modes](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html): 0–13 control how Tesseract interprets the layout |

**subprocess.run() parameters:**

| Parameter | Meaning |
|-----------|---------|
| `capture_output=True` | Captures both stdout (the extracted text) and stderr (warnings/errors) |
| `text=True` | Returns stdout/stderr as strings instead of bytes |
| `timeout=30` | Kill the process if it runs longer than 30 seconds (prevents hanging on corrupt images) |

**Timing:** `time.time()` records the wall-clock time before and after. The difference, multiplied by 1000, gives milliseconds.

```python
        os.unlink(tmp_path)
```

**Line 54:** [`os.unlink()`](https://docs.python.org/3/library/os.html#os.unlink) deletes the temporary file. Always clean up temp files to prevent disk space leaks in long-running containers.

```python
        extracted_text = result.stdout.strip()

        if result.returncode != 0 and not extracted_text:
            return {
                "error": "Tesseract OCR failed: " + result.stderr.strip(),
                "processing_time_ms": elapsed_ms
            }
```

**Lines 56–62:** `result.stdout` contains Tesseract's output. `.strip()` removes leading/trailing whitespace. If Tesseract returned a non-zero exit code AND produced no text, something went wrong — return the error from stderr. (Sometimes Tesseract returns code 1 but still outputs text — we keep that text.)

```python
        return {
            "text": extracted_text,
            "processing_time_ms": elapsed_ms,
            "filename": filename,
            "text_length": len(extracted_text),
            "word_count": len(extracted_text.split()) if extracted_text else 0
        }

    except Exception as e:
        return {"error": str(e)}
```

**Lines 64–73:** The successful response includes:

- **`text`** — The extracted text content.
- **`processing_time_ms`** — How long Tesseract took (server-side only; the frontend also measures total round-trip time including network).
- **`word_count`** — `str.split()` splits on any whitespace and returns a list; `len()` counts the words.

The outer `try/except` catches any unexpected errors (corrupt base64, disk errors, etc.) and returns them in a structured format rather than crashing.

---

### 5.5 `lambda/pdf_handler.py` — Direct PDF Text Extraction

This handler extracts embedded text directly from PDF files using PyMuPDF — no OCR needed. This works for PDFs created digitally (from Word, web browsers, etc.) where text is stored as searchable characters.

```python
import base64
import os
import tempfile
import time

import fitz  # PyMuPDF
```

**Lines 1–6:** Standard library imports plus PyMuPDF. As noted earlier, `fitz` is the import name for [PyMuPDF](https://pymupdf.readthedocs.io/).

```python
def pdf_handler(event, context):
```

**Line 9:** Same Lambda handler signature. Takes the JSON event and an unused context.

```python
        payload = event
        pdf_data = payload.get("pdf", "")
        filename = payload.get("filename", "unknown.pdf")

        if not pdf_data:
            return {"error": "No PDF data provided"}

        if "," in pdf_data:
            pdf_data = pdf_data.split(",", 1)[1]

        pdf_bytes = base64.b64decode(pdf_data)
```

**Lines 13–24:** Same pattern as the image handler: extract the `pdf` field, strip the data URL prefix, decode base64 to raw bytes.

```python
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
```

**Lines 27–29:** Write PDF bytes to a temporary file. PyMuPDF's [`fitz.open()`](https://pymupdf.readthedocs.io/en/latest/document.html#Document.__init__) can accept either a file path or bytes — we use a file path here for consistency with the OCR handler.

```python
        total_start = time.time()

        doc = fitz.open(tmp_path)
        page_count = len(doc)
```

**Lines 32–35:** [`fitz.open()`](https://pymupdf.readthedocs.io/en/latest/document.html#Document.__init__) opens the PDF and returns a `Document` object. `len(doc)` gives the total number of pages.

```python
        pages = []
        full_text_parts = []
        total_word_count = 0
        total_char_count = 0

        for i, page in enumerate(doc):
            page_start = time.time()
            text = page.get_text("text").strip()
            page_ms = round((time.time() - page_start) * 1000, 2)
```

**Lines 37–45:** Iterates over every page. [`page.get_text("text")`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_text) extracts embedded text from the page. The `"text"` parameter specifies plain text output (other options: `"html"`, `"dict"`, `"json"`, `"xml"`). Each page's extraction time is measured independently.

```python
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

**Lines 47–59:** Accumulates per-page statistics and builds the `pages` array. Each page entry includes its text, counts, and extraction time.

```python
        doc.close()
        total_ms = round((time.time() - total_start) * 1000, 2)
        os.unlink(tmp_path)
        full_text = "\n\n".join(full_text_parts)
```

**Lines 61–68:** Close the document, measure total time, delete the temp file, and join all page texts with double newlines as separators.

```python
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
```

**Lines 70–79:** Returns the full result. The `pages` array is included so the frontend can display a per-page timing breakdown.

---

### 5.6 `lambda/pdf_ocr_handler.py` — PDF→Image→OCR Pipeline

This is the most complex handler. It solves the problem of scanned PDFs (where `get_text()` returns nothing) by rendering each page as a high-resolution image and then running Tesseract on each image.

```python
import base64
import os
import subprocess
import tempfile
import time

import fitz  # PyMuPDF
```

**Lines 1–7:** Imports both `subprocess` (for running Tesseract) and `fitz` (for rendering PDF pages to images).

#### Helper Function: `run_tesseract()`

```python
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
```

**Lines 21–36:** Extracted into its own function for reuse. Same Tesseract command as `handler.py`, but with a 60-second timeout (PDF pages at 300 DPI can be larger and slower to process). Returns a tuple of `(text, elapsed_ms)` — the [type hint](https://docs.python.org/3/library/typing.html) `tuple[str, float]` documents this.

#### Helper Function: `extract_page_image()`

```python
def extract_page_image(page, dpi: int = 300) -> tuple[bytes, float]:
    """Render a PDF page to a PNG image. Returns (png_bytes, elapsed_ms)."""
    start = time.time()
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    elapsed_ms = round((time.time() - start) * 1000, 2)
    return png_bytes, elapsed_ms
```

**Lines 39–46:** Renders a single PDF page to a PNG image. This is the key to the pipeline.

- **Line 42: `fitz.Matrix(dpi / 72, dpi / 72)`** — Creates a [transformation matrix](https://pymupdf.readthedocs.io/en/latest/matrix.html). PDFs internally use 72 points per inch. To render at 300 DPI, we scale by `300/72 ≈ 4.17x`. This produces an image ~4x larger than the default, which dramatically improves OCR accuracy.
- **Line 43: [`page.get_pixmap(matrix=mat)`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_pixmap)** — Renders the page as a raster image ([Pixmap](https://pymupdf.readthedocs.io/en/latest/pixmap.html)). The matrix controls resolution.
- **Line 44: `pix.tobytes("png")`** — Serializes the pixmap as PNG bytes.

**Why 300 DPI?** This is the standard scanning resolution for OCR. At 72 DPI (default), characters are too small for Tesseract to recognize reliably. At 300 DPI, a standard letter-size page renders to approximately 2550×3300 pixels (~65KB PNG), which is the sweet spot for accuracy vs. speed.

#### Main Handler: `pdf_ocr_handler()`

```python
def pdf_ocr_handler(event, context):
```

**Line 49:** The main handler function.

```python
        payload = event
        pdf_data = payload.get("pdf", "")
        filename = payload.get("filename", "unknown.pdf")
        dpi = payload.get("dpi", 300)
```

**Lines 56–59:** Extracts parameters. Note the `dpi` parameter — callers can optionally override the rendering resolution (e.g., `150` for faster but less accurate extraction, or `600` for maximum quality).

```python
        if not pdf_data:
            return {"error": "No PDF data provided"}

        if "," in pdf_data:
            pdf_data = pdf_data.split(",", 1)[1]

        pdf_bytes = base64.b64decode(pdf_data)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            pdf_path = tmp.name
```

**Lines 61–73:** Same validation and temp file pattern as the other handlers.

```python
        total_start = time.time()

        doc = fitz.open(pdf_path)
        page_count = len(doc)

        pages = []
        full_text_parts = []
        total_word_count = 0
        total_char_count = 0
        total_extract_ms = 0
        total_ocr_ms = 0
```

**Lines 75–85:** Opens the PDF and initializes accumulators. Note the two separate timing accumulators: `total_extract_ms` (image rendering) and `total_ocr_ms` (Tesseract processing). This lets us measure the two stages independently.

```python
        for i, page in enumerate(doc):
            page_start = time.time()

            # Step 1: Render page to image
            png_bytes, extract_ms = extract_page_image(page, dpi)
            total_extract_ms += extract_ms
```

**Lines 87–92:** For each page, first render it to a PNG image. `extract_ms` measures how long PyMuPDF took.

```python
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

**Lines 94–104:** Write the PNG to a temp file (Tesseract reads from files, not memory), run OCR, then immediately delete the temp image. Each page's temp image lives only as long as needed.

```python
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
```

**Lines 106–123:** Records per-page results. Each page entry includes three timing dimensions:

- **`image_extract_ms`** — How long PyMuPDF took to render this page.
- **`ocr_ms`** — How long Tesseract took to recognize text on this page.
- **`page_total_ms`** — Wall-clock total for this page (includes temp file I/O overhead).

The `image_size_bytes` tells you how large the rendered PNG was — useful for debugging (larger images = slower OCR).

```python
        doc.close()
        os.unlink(pdf_path)

        pipeline_ms = round((time.time() - total_start) * 1000, 2)
        full_text = "\n\n".join(full_text_parts)
```

**Lines 125–129:** Close the PDF, delete the temp file, calculate total pipeline time.

```python
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
```

**Lines 131–147:** The response includes a `timing` object with aggregate statistics:

- **`pipeline_ms`** — Total server-side processing time.
- **`total_image_extract_ms`** — Sum of all page rendering times.
- **`total_ocr_ms`** — Sum of all OCR times.
- **`avg_*_per_page_ms`** — Averages for performance profiling.

The `max(page_count, 1)` prevents division by zero if a PDF has 0 pages.

---

### 5.7 `nginx/default.conf` — Reverse Proxy Configuration

Nginx serves two roles: static file server (for the HTML/JS frontend) and reverse proxy (forwarding API requests to the Lambda container).

**Reference:** [Nginx Beginner's Guide](https://nginx.org/en/docs/beginners_guide.html) · [Proxy Module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)

```nginx
server {
    listen 80;
    server_name localhost;
```

**Lines 1–3:** Defines a [server block](https://nginx.org/en/docs/http/ngx_http_core_module.html#server) that listens on port 80. `server_name localhost` means this configuration handles requests to `localhost` (which is all requests in our setup).

```nginx
    root /usr/share/nginx/html;
    index index.html;

    client_max_body_size 50m;
```

**Lines 5–8:**

- **`root`** — [Document root](https://nginx.org/en/docs/http/ngx_http_core_module.html#root). Where Nginx looks for static files. Our `docker-compose.yml` mounts `./app` here.
- **`index`** — Default file served when a directory is requested.
- **`client_max_body_size`** — [Maximum upload size](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size). Set to 50MB to handle large PDFs. Without this, Nginx returns `413 Request Entity Too Large` for uploads over the default 1MB.

```nginx
    location / {
        try_files $uri $uri/ /index.html;
    }
```

**Lines 10–12:** [Location block](https://nginx.org/en/docs/http/ngx_http_core_module.html#location) for the root path. [`try_files`](https://nginx.org/en/docs/http/ngx_http_core_module.html#try_files) tells Nginx: first try the exact file (`$uri`), then try it as a directory (`$uri/`), and if neither exists, serve `index.html`. This is a common pattern for single-page applications (SPAs).

```nginx
    location /api/ocr {
        proxy_pass http://lambda:9000/2015-03-31/functions/ocr-service/invocations;
```

**Lines 15–16:** [Reverse proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass) configuration. When the browser sends a POST to `/api/ocr`, Nginx forwards it to the Lambda container at the full Lambda invoke URL.

**How does `http://lambda:9000` resolve?** Docker Compose creates a [bridge network](https://docs.docker.com/compose/networking/) where containers can reach each other by service name. The service named `lambda` in `docker-compose.yml` is reachable at hostname `lambda`.

```nginx
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Content-Type "application/json";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
```

**Lines 17–21:**

- **`proxy_http_version 1.1`** — Use HTTP/1.1 for the upstream connection (supports keep-alive).
- **`proxy_set_header Host $host`** — Forwards the original `Host` header.
- **`proxy_read_timeout 300s`** — Wait up to 5 minutes for the Lambda container to respond. OCR on large multi-page PDFs can be slow.
- **`proxy_send_timeout 300s`** — Wait up to 5 minutes for the request body to be sent.

```nginx
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type" always;
        if ($request_method = 'OPTIONS') { return 204; }
```

**Lines 23–26:** [CORS (Cross-Origin Resource Sharing)](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS) headers. Even though the browser and API are on the same origin (`localhost:8080`), these headers prevent issues if you ever access the API from a different origin. The `OPTIONS` preflight response returns `204 No Content`.

The remaining two `location` blocks (`/api/pdf` and `/api/pdf-ocr`) follow the identical pattern, routing to different Lambda functions.

---

### 5.8 `app/index.html` — Frontend Application

The frontend is a single HTML file containing all markup, styles, and JavaScript. It implements a **three-tab interface** with drag-and-drop upload, live progress indicators, and rich results display.

Each tab has its own color identity:

| Tab | Color | API Endpoint | Purpose |
|-----|-------|-------------|---------|
| **Image OCR** | 🟢 Green (`#6ee7b7`) | `POST /api/ocr` | Upload images, run Tesseract |
| **PDF Text** | 🔵 Blue (`#60a5fa`) | `POST /api/pdf` | Upload PDFs, extract embedded text directly (no OCR) |
| **PDF OCR** | 🩷 Pink (`#f472b6`) | `POST /api/pdf-ocr` | Upload PDFs, render pages as images, run Tesseract |

#### HTML Head — Configuration & Styles

```html
<script src="https://cdn.tailwindcss.com"></script>
```

Loads the [Tailwind CSS CDN](https://tailwindcss.com/docs/installation/play-cdn). This includes a JIT (Just-In-Time) compiler that runs in the browser, generating CSS from class names. For production, you'd use the Tailwind CLI for better performance, but the CDN is perfect for self-contained demos.

```html
<script>
    tailwind.config = {
        theme: {
            extend: {
                fontFamily: { display: ['Outfit','sans-serif'], mono: ['JetBrains Mono','monospace'] },
                colors: {
                    surface: { 900:'#0a0a0f', 800:'#12121a', 700:'#1a1a26', 600:'#242436' },
                    accent: { DEFAULT:'#6ee7b7', dim:'#34d399' },
                    pdf: { DEFAULT:'#f472b6', dim:'#ec4899' }
                }
            }
        }
    }
</script>
```

[Tailwind configuration](https://tailwindcss.com/docs/configuration). Extends the default theme with custom colors (dark surface palette, green accent for images, pink accent for PDFs) and custom fonts. These become usable as classes like `bg-surface-800`, `text-accent`, `text-pdf`, `font-display`, `font-mono`.

The `<style>` block defines custom CSS that Tailwind can't handle with utility classes alone: animations (`@keyframes`), custom scrollbar styles, the scanning line effect, and gradient glow effects.

#### JavaScript — Tab Switching

```javascript
const TAB_CFG = {
    image:   { tab:'tabImage',   section:'sectionImage',   cls:'tab-active-green' },
    pdftext: { tab:'tabPdfText', section:'sectionPdfText', cls:'tab-active-blue'  },
    pdfocr:  { tab:'tabPdfOcr',  section:'sectionPdfOcr',  cls:'tab-active-pink'  },
};
function switchTab(active) {
    Object.entries(TAB_CFG).forEach(([key, cfg]) => {
        // show/hide sections, apply active/inactive styles
    });
}
```

A data-driven approach: the `TAB_CFG` object maps tab keys to their DOM element IDs and active CSS class. `switchTab()` iterates all entries, showing the active section and hiding the rest. This avoids repetitive if/else chains and makes adding new tabs trivial.

#### JavaScript — File Handling (Image)

```javascript
imgDropZone.addEventListener('dragover', e => {
    e.preventDefault();
    imgDropZone.classList.add('dragover-img');
});
```

The [Drag and Drop API](https://developer.mozilla.org/en-US/docs/Web/API/HTML_Drag_and_Drop_API) requires calling `e.preventDefault()` on `dragover` to indicate the element accepts drops. The `dragover-img` class triggers a visual highlight (green border glow).

```javascript
function handleImageFile(file) {
    imgFile = file;
    const reader = new FileReader();
    reader.onload = e => {
        imgBase64 = e.target.result;
        document.getElementById('imgPreview').src = imgBase64;
        // ... show preview, hide prompt
    };
    reader.readAsDataURL(file);
}
```

[`FileReader.readAsDataURL()`](https://developer.mozilla.org/en-US/docs/Web/API/FileReader/readAsDataURL) asynchronously reads the file and produces a base64 data URL like `data:image/png;base64,iVBOR...`. This string is both:
1. Set as the `src` of an `<img>` tag for preview.
2. Sent to the backend as the image payload.

#### JavaScript — API Call (Image OCR)

```javascript
async function callOcrLambda(imageBase64, filename) {
    const r = await fetch('/api/ocr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: imageBase64, filename }),
    });
    if (!r.ok) throw new Error('Lambda failed (' + r.status + '): ' + await r.text());
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    return d;
}
```

Uses the [Fetch API](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API) to POST JSON to `/api/ocr`. Nginx proxies this to the Lambda container. The function checks both HTTP-level errors (`r.ok`) and application-level errors (`d.error`).

#### JavaScript — API Call (PDF Text Extract — no OCR)

```javascript
const r = await fetch('/api/pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pdf: b64, filename: file.name }),
});
```

Posts to `/api/pdf`, which routes to `pdf_handler.py`. This call is typically 100x faster than the OCR pipeline because it reads embedded text directly using `page.get_text("text")` — no rendering or Tesseract involved. The response includes per-page `extraction_time_ms` values (typically sub-millisecond), which the UI displays as blue timing bars.

If the result comes back empty, the PDF likely contains scanned images rather than embedded text. The UI displays a hint: *(No text found — try PDF OCR tab for scanned documents)*.

#### JavaScript — API Call (PDF→Image→OCR)

```javascript
async function callPdfOcrLambda(pdfBase64, filename) {
    const r = await fetch('/api/pdf-ocr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pdf: pdfBase64, filename }),
    });
    if (!r.ok) throw new Error('Lambda failed (' + r.status + '): ' + await r.text());
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    return d;
}
```

Nearly identical to the image call, but posts to `/api/pdf-ocr` with a `pdf` field instead of `image`. The response includes the `timing` object and `pages` array that the results section renders.

#### JavaScript — Timing Measurement

```javascript
const t0 = performance.now();
const data = await callPdfOcrLambda(pdfBase64, pdfFile.name);
const roundtripMs = (performance.now() - t0).toFixed(2);
```

[`performance.now()`](https://developer.mozilla.org/en-US/docs/Web/API/Performance/now) provides microsecond-precision timing in the browser. The difference gives the **total round-trip time** (upload + proxy + processing + download). This is contrasted with the server-side `pipeline_ms` from the response — the difference is network overhead.

#### JavaScript — Results Rendering (PDF)

```javascript
// Build per-page table with timing bars
const pages = data.pages || [];
const maxTime = Math.max(...pages.map(p => p.image_extract_ms + p.ocr_ms), 1);

pages.forEach(p => {
    const extractPct = Math.max((p.image_extract_ms / maxTime) * 100, 1);
    const ocrPct = Math.max((p.ocr_ms / maxTime) * 100, 1);
    // ... create table row with colored bars
});
```

This code builds a visual timing breakdown where each page gets a horizontal bar chart. The bar widths are proportional to the slowest page (`maxTime`), so you can visually compare extraction vs. OCR time across pages. Purple bars represent image extraction, pink bars represent OCR processing.

---

### 5.9 `ocr_client.py` — CLI Client

A command-line tool that sends images and PDFs to the running Docker service and outputs results as CSV. PDFs default to direct text extraction (fast, no OCR). Use `--pdf-ocr` for scanned PDFs.

```python
#!/usr/bin/env python3
```

**Line 1:** [Shebang line](https://en.wikipedia.org/wiki/Shebang_(Unix)). On Unix systems, this lets you run `./ocr_client.py` directly without typing `python3`.

**Key CLI arguments:**

| Flag | Default | Description |
|------|---------|-------------|
| `files` | (required) | Image and/or PDF file paths (supports globs like `*.png`) |
| `--pdf-ocr` | off | Use PDF→Image→OCR pipeline for PDFs (slower, works on scanned docs) |
| `--direct` | off | Bypass Nginx, call Lambda container on `:9000` directly |
| `-o FILE` | stdout | Write CSV to a file instead of stdout |
| `--no-header` | off | Omit CSV header row |

The `method` column in CSV output distinguishes between the three services: `image-ocr`, `pdf-text`, or `pdf-ocr`.

```python
import argparse, base64, csv, os, sys, time
```

**Line 15:** Standard library imports:

| Module | Purpose | Docs |
|--------|---------|------|
| `argparse` | Parse command-line arguments | [argparse](https://docs.python.org/3/library/argparse.html) |
| `csv` | Write CSV output | [csv](https://docs.python.org/3/library/csv.html) |

```python
try:
    import requests
except ImportError:
    print("Error: pip install requests", file=sys.stderr); sys.exit(1)
```

**Lines 17–20:** Graceful handling of missing dependency. The [`requests`](https://requests.readthedocs.io/) library is not in Python's standard library — if it's not installed, print a helpful message instead of crashing with a traceback.

```python
PDF_EXTS = {".pdf"}
IMG_EXTS = {".png",".jpg",".jpeg",".tiff",".tif",".bmp",".gif",".webp"}
```

**Lines 22–23:** File extension sets for type detection. Using [sets](https://docs.python.org/3/library/stdtypes.html#set) gives O(1) lookup — `ext in IMG_EXTS` is a constant-time check.

```python
def encode(fp):
    with open(fp,"rb") as f: return base64.b64encode(f.read()).decode()
```

**Lines 25–26:** Reads a file as raw bytes (`"rb"` mode) and encodes to base64. `.decode()` converts the base64 bytes to a string (JSON doesn't accept byte literals).

```python
def call_pdf_ocr(path, url):
    fn = os.path.basename(path); b64 = encode(path); sz = os.path.getsize(path)
    t=time.time(); r=requests.post(url,json={"pdf":b64,"filename":fn},timeout=300)
    ms=round((time.time()-t)*1000,2); r.raise_for_status(); d=r.json()
    if "error" in d: raise RuntimeError(d["error"])
    d["total_time_ms"]=ms; d["file_size_actual"]=sz; return d
```

**Lines 35–40:** Sends a PDF to the service. [`requests.post(url, json=...)`](https://requests.readthedocs.io/en/latest/user/quickstart/#more-complicated-post-requests) automatically serializes the dictionary to JSON and sets the `Content-Type` header. `raise_for_status()` throws an exception for HTTP 4xx/5xx responses.

The main function uses [argparse](https://docs.python.org/3/library/argparse.html) to define command-line flags, then iterates over input files, detects type by extension, calls the appropriate service, and writes results as CSV.

```python
    fields = ["filename","type","file_size","total_ms","pipeline_ms","img_extract_ms","ocr_ms","pages","words","chars","text"]
    out = open(a.output,"w",newline="",encoding="utf-8") if a.output else sys.stdout
    w = csv.DictWriter(out, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
```

**Lines 51–53:** [`csv.DictWriter`](https://docs.python.org/3/library/csv.html#csv.DictWriter) writes dictionaries as CSV rows. `QUOTE_MINIMAL` only adds quotes when a field contains the delimiter or newlines. Progress messages are written to `stderr` so piping stdout to a file produces clean CSV: `python ocr_client.py *.pdf > results.csv`.

---

## 6. Data Flow Diagrams

### Image OCR — Complete Data Flow

```
┌────────────┐     ┌──────────────────┐     ┌────────────────────────────────────────┐
│  Browser   │     │  Nginx :8080     │     │  Lambda :9000                          │
│            │     │                  │     │                                        │
│ FileReader │     │                  │     │  server.py                             │
│ readAsData │     │                  │     │    │                                   │
│ URL(file)  │     │                  │     │    ▼                                   │
│    │       │     │                  │     │  HANDLERS["ocr-service"]               │
│    ▼       │     │                  │     │    │                                   │
│ base64     │     │                  │     │    ▼                                   │
│ data URL   │     │                  │     │  handler.py                            │
│    │       │     │                  │     │    │                                   │
│    ▼       │     │                  │     │    ├─ strip "data:image/png;base64,"   │
│ fetch()    │────▶│ POST /api/ocr   │────▶│    ├─ base64.b64decode() → bytes       │
│ POST JSON  │     │ proxy_pass to   │     │    ├─ write to /tmp/tmpXXXX.png        │
│ {image,    │     │ lambda:9000/    │     │    ├─ subprocess.run(tesseract ...)     │
│  filename} │     │ .../ocr-service │     │    ├─ ⏱ measure elapsed_ms             │
│            │     │ /invocations    │     │    ├─ os.unlink(tmp file)              │
│            │◀────│                 │◀────│    └─ return {text, processing_time_ms, │
│ Display    │     │ CORS headers    │     │         word_count, text_length}        │
│ results +  │     │ added           │     │                                        │
│ timing     │     │                  │     │                                        │
└────────────┘     └──────────────────┘     └────────────────────────────────────────┘
```

### PDF Text Extract (no OCR) — Complete Data Flow

```
┌────────────┐     ┌──────────────────┐     ┌────────────────────────────────────────┐
│  Browser   │     │  Nginx :8080     │     │  Lambda :9000                          │
│            │     │                  │     │                                        │
│ FileReader │     │                  │     │  server.py                             │
│ readAsData │     │                  │     │    │                                   │
│ URL(pdf)   │     │                  │     │    ▼                                   │
│    │       │     │                  │     │  HANDLERS["pdf-extract"]               │
│    ▼       │     │                  │     │    │                                   │
│ fetch()    │────▶│ POST /api/pdf   │────▶│    ▼                                   │
│ POST JSON  │     │ proxy_pass to   │     │  pdf_handler.py                        │
│ {pdf,      │     │ lambda:9000/    │     │    │                                   │
│  filename} │     │ .../pdf-extract │     │    ├─ strip data URL prefix             │
│            │     │ /invocations    │     │    ├─ base64.b64decode() → PDF bytes    │
│            │     │                  │     │    ├─ write to /tmp/tmpXXXX.pdf        │
│            │     │                  │     │    ├─ fitz.open(pdf_path)              │
│            │     │                  │     │    │                                   │
│            │     │                  │     │    │  ┌─ FOR EACH PAGE ──────────┐     │
│            │     │                  │     │    │  │ page.get_text("text")    │     │
│            │     │                  │     │    │  │ ⏱ extraction_time_ms     │     │
│            │     │                  │     │    │  │ (no rendering, no OCR)   │     │
│            │     │                  │     │    │  └──────────────────────────┘     │
│            │     │                  │     │    │                                   │
│            │     │                  │     │    ├─ doc.close(), delete temp PDF     │
│            │◀────│                 │◀────│    └─ return {text, processing_time_ms, │
│ Render     │     │ CORS headers    │     │         page_count, pages[per-page]}    │
│ per-page   │     │                  │     │                                        │
│ timing     │     │                  │     │  ~100x faster than OCR pipeline        │
└────────────┘     └──────────────────┘     └────────────────────────────────────────┘
```

### PDF→Image→OCR — Complete Data Flow

```
┌────────────┐     ┌──────────────────┐     ┌────────────────────────────────────────────┐
│  Browser   │     │  Nginx :8080     │     │  Lambda :9000                              │
│            │     │                  │     │                                            │
│ FileReader │     │                  │     │  server.py                                 │
│ readAsData │     │                  │     │    │                                       │
│ URL(pdf)   │     │                  │     │    ▼                                       │
│    │       │     │                  │     │  HANDLERS["pdf-ocr"]                       │
│    ▼       │     │                  │     │    │                                       │
│ fetch()    │────▶│ POST /api/pdf-ocr│────▶│    ▼                                       │
│ POST JSON  │     │ proxy_pass to   │     │  pdf_ocr_handler.py                        │
│ {pdf,      │     │ lambda:9000/    │     │    │                                       │
│  filename} │     │ .../pdf-ocr/    │     │    ├─ strip data URL prefix                │
│            │     │ invocations     │     │    ├─ base64.b64decode() → PDF bytes        │
│            │     │                  │     │    ├─ write to /tmp/tmpXXXX.pdf            │
│            │     │                  │     │    ├─ fitz.open(pdf_path)                  │
│            │     │                  │     │    │                                       │
│            │     │                  │     │    │  ┌─ FOR EACH PAGE ──────────────┐     │
│            │     │                  │     │    │  │                              │     │
│            │     │                  │     │    │  │ Step 1: extract_page_image() │     │
│            │     │                  │     │    │  │  fitz.Matrix(300/72, 300/72) │     │
│            │     │                  │     │    │  │  page.get_pixmap(matrix)     │     │
│            │     │                  │     │    │  │  pix.tobytes("png")          │     │
│            │     │                  │     │    │  │  ⏱ image_extract_ms          │     │
│            │     │                  │     │    │  │         │                    │     │
│            │     │                  │     │    │  │         ▼                    │     │
│            │     │                  │     │    │  │ Step 2: write PNG to /tmp    │     │
│            │     │                  │     │    │  │         │                    │     │
│            │     │                  │     │    │  │         ▼                    │     │
│            │     │                  │     │    │  │ Step 3: run_tesseract()      │     │
│            │     │                  │     │    │  │  subprocess.run(tesseract)   │     │
│            │     │                  │     │    │  │  ⏱ ocr_ms                   │     │
│            │     │                  │     │    │  │         │                    │     │
│            │     │                  │     │    │  │         ▼                    │     │
│            │     │                  │     │    │  │ Step 4: delete temp PNG      │     │
│            │     │                  │     │    │  │  collect {text, timing}      │     │
│            │     │                  │     │    │  └──────────────────────────────┘     │
│            │     │                  │     │    │                                       │
│            │     │                  │     │    ├─ doc.close()                          │
│            │     │                  │     │    ├─ delete temp PDF                      │
│            │◀────│                 │◀────│    └─ return {text, timing{pipeline_ms,    │
│ Render     │     │ CORS headers    │     │         total_image_extract_ms,             │
│ timing     │     │                  │     │         total_ocr_ms}, pages[{per-page}]}  │
│ table +    │     │                  │     │                                            │
│ bars       │     │                  │     │                                            │
└────────────┘     └──────────────────┘     └────────────────────────────────────────────┘
```

### Timing Measurement Points

```
                    Image OCR / PDF OCR
                    ═══════════════════
Browser ◀──────────── Round-trip (performance.now()) ────────────▶ Browser
        │                                                        │
        ├──── Network upload ────▶│                     │◀── Network download ──┤
                                  │                     │
                          Lambda  ◀── pipeline_ms ──▶  Lambda
                                  │                     │
                          Per page:                     │
                          ├── image_extract_ms ──▶│     │  (PDF OCR only)
                          │   (PyMuPDF render)    │     │
                          ├── ocr_ms ────────────▶│     │
                          │   (Tesseract)         │     │
                          ├── page_total_ms ─────▶│     │
                              (extract + ocr + io)

                    PDF Text Extract (no OCR)
                    ═════════════════════════
Browser ◀──────────── Round-trip (performance.now()) ────────────▶ Browser
        │                                                        │
                          Lambda  ◀── processing_time_ms ──▶  Lambda
                                  │                     │
                          Per page:                     │
                          ├── extraction_time_ms ▶│     │  (just get_text(),
                              (PyMuPDF get_text)        │   typically <1ms/page)
```

**Speed comparison** (typical 3-page PDF):

| Service | Processing Time | Why |
|---------|----------------|-----|
| PDF Text | ~1–10 ms | Reads embedded text directly from PDF structure |
| PDF OCR | ~3,000 ms | Renders 300 DPI images (~150ms each) + Tesseract (~800ms each) |

---

## 7. How to Run

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (includes Docker Compose v2)

### Start the services

```bash
cd ocr-app
docker compose up --build
```

This builds the Lambda container (installs Tesseract, PyMuPDF, Flask), pulls the Nginx image, and starts both. First build takes 1–2 minutes; subsequent starts take ~10 seconds.

### Use the web interface

Open **http://localhost:8080** in your browser.

Three tabs are available:

1. **Image OCR** (green) — Drop an image, click **Extract Text**. Runs Tesseract directly.
2. **PDF Text** (blue) — Drop a PDF, click **Extract Text (No OCR)**. Reads embedded text instantly. Use for digitally-created PDFs.
3. **PDF OCR** (pink) — Drop a PDF, click **Extract via OCR**. Renders each page as 300 DPI images, then runs Tesseract. Use for scanned/image-based PDFs.

### Use the CLI client

```bash
pip install requests

# Single image (OCR)
python ocr_client.py screenshot.png

# PDF — direct text extraction (default, fast, no OCR)
python ocr_client.py document.pdf

# PDF — render pages as images → OCR (slow, for scanned PDFs)
python ocr_client.py document.pdf --pdf-ocr

# Batch processing with CSV output
python ocr_client.py *.png *.pdf -o results.csv

# Scanned PDFs + images together
python ocr_client.py scan.png scanned.pdf --pdf-ocr -o results.csv

# Bypass Nginx, call Lambda directly
python ocr_client.py scan.png --direct
```

### Stop the services

```bash
docker compose down
```

---

## 8. Glossary

| Term | Definition |
|------|-----------|
| **OCR** | Optical Character Recognition — converting images of text to machine-readable text |
| **Tesseract** | Google's open-source OCR engine, originally developed by HP Labs (1985–2006) |
| **PyMuPDF / fitz** | Python bindings for the MuPDF rendering engine, used for PDF manipulation |
| **LSTM** | Long Short-Term Memory — the neural network architecture Tesseract v4+ uses for recognition |
| **DPI** | Dots Per Inch — resolution of a rendered image. 300 DPI is standard for OCR |
| **Base64** | Binary-to-text encoding that represents binary data as ASCII characters (33% size increase) |
| **Data URL** | A URI scheme (`data:mime;base64,...`) that embeds file data inline in web pages |
| **Reverse Proxy** | A server that forwards client requests to backend services (Nginx in our case) |
| **CORS** | Cross-Origin Resource Sharing — HTTP headers that control which origins can access an API |
| **WSGI** | Web Server Gateway Interface — Python's standard for web server ↔ application communication |
| **PSM** | Page Segmentation Mode — how Tesseract interprets the layout of text on a page |
| **OEM** | OCR Engine Mode — which Tesseract recognition engine to use (legacy, LSTM, or both) |
| **Pixmap** | A raster image representation in memory (PyMuPDF's internal format) |
| **Healthcheck** | A periodic test that Docker runs to verify a container is functioning correctly |
| **Bind Mount** | Docker feature that maps a host directory into a container's filesystem |
| **Layer (Docker)** | Each Dockerfile instruction creates an immutable filesystem layer; layers are cached for fast rebuilds |

---

## References & Further Reading

- [Tesseract OCR Documentation](https://tesseract-ocr.github.io/tessdoc/)
- [Tesseract Command-Line Usage](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
- [PyMuPDF Documentation](https://pymupdf.readthedocs.io/en/latest/)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose File Reference](https://docs.docker.com/compose/compose-file/)
- [Nginx Documentation](https://nginx.org/en/docs/)
- [Nginx Reverse Proxy Guide](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [MDN: Fetch API](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API)
- [MDN: FileReader API](https://developer.mozilla.org/en-US/docs/Web/API/FileReader)
- [MDN: Drag and Drop API](https://developer.mozilla.org/en-US/docs/Web/API/HTML_Drag_and_Drop_API)
- [MDN: CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS)
- [MDN: Data URLs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/Data_URLs)
- [AWS Lambda Handler (Python)](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html)
- [AWS Lambda Invoke API](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html)
- [Python subprocess Module](https://docs.python.org/3/library/subprocess.html)
- [Python base64 Module](https://docs.python.org/3/library/base64.html)
- [Python tempfile Module](https://docs.python.org/3/library/tempfile.html)
- [Requests Library](https://requests.readthedocs.io/)

---

*Tutorial generated for OCR Extract v1.0 — Docker Compose OCR Service with Image and PDF Pipeline*
