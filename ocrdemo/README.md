# OCR Extract — Image & PDF Text Extraction Service

## Quick Start

```bash
cd ocr-app
docker compose up --build
```

Open **http://localhost:8080** — ready in ~10 seconds.

## Architecture

```
                    ┌───────────────────────────────────┐
                    │       Lambda Service :9000         │
  Browser ──nginx──▶│                                   │
                    │  /api/ocr     → ocr-service       │
                    │                 Image → Tesseract  │
                    │                                   │
                    │  /api/pdf     → pdf-extract        │
                    │                 PDF → get_text()   │
                    │                 (no OCR, fast)     │
                    │                                   │
                    │  /api/pdf-ocr → pdf-ocr           │
                    │                 PDF → Images → OCR │
                    └───────────────────────────────────┘
```

## Three Extraction Services

| Tab | Endpoint | Method | Use When |
|-----|----------|--------|----------|
| 🟢 Image OCR | `/api/ocr` | Tesseract on image | Screenshots, photos |
| 🔵 PDF Text | `/api/pdf` | PyMuPDF `get_text()` | Digital PDFs (Word, web) |
| 🩷 PDF OCR | `/api/pdf-ocr` | Render → Tesseract | Scanned/image PDFs |

## CLI Client

```bash
pip install requests

python ocr_client.py image.png              # Image OCR
python ocr_client.py document.pdf           # PDF text extract (fast, no OCR)
python ocr_client.py document.pdf --pdf-ocr # PDF → Image → OCR (scanned docs)
python ocr_client.py *.png *.pdf -o out.csv # Batch to CSV
```

## Full Tutorial

See [TUTORIAL.md](TUTORIAL.md) — 1,500+ line line-by-line walkthrough with data flow diagrams and linked references.
