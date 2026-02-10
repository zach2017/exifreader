#!/usr/bin/env python3
"""
OCR/PDF CLI Client — Send images or PDFs to the Lambda service, print CSV.

Usage:
    python ocr_client.py image.png                    # Image OCR
    python ocr_client.py document.pdf                 # PDF text extract (no OCR, default)
    python ocr_client.py document.pdf --pdf-ocr       # PDF → Image → OCR pipeline
    python ocr_client.py *.png *.pdf -o results.csv   # Batch to CSV
    python ocr_client.py doc.pdf --direct              # Bypass nginx

Requires: pip install requests
"""

import argparse, base64, csv, os, sys, time

try:
    import requests
except ImportError:
    print("Error: pip install requests", file=sys.stderr); sys.exit(1)

PDF_EXTS = {".pdf"}
IMG_EXTS = {".png",".jpg",".jpeg",".tiff",".tif",".bmp",".gif",".webp"}

def encode(fp):
    with open(fp,"rb") as f: return base64.b64encode(f.read()).decode()

def call_img_ocr(path, url):
    fn = os.path.basename(path); b64 = encode(path); sz = os.path.getsize(path)
    t=time.time(); r=requests.post(url,json={"image":b64,"filename":fn},timeout=120)
    ms=round((time.time()-t)*1000,2); r.raise_for_status(); d=r.json()
    if "error" in d: raise RuntimeError(d["error"])
    d["total_time_ms"]=ms; d["file_size_bytes"]=sz; return d

def call_pdf_text(path, url):
    """Direct text extraction (no OCR)."""
    fn = os.path.basename(path); b64 = encode(path); sz = os.path.getsize(path)
    t=time.time(); r=requests.post(url,json={"pdf":b64,"filename":fn},timeout=300)
    ms=round((time.time()-t)*1000,2); r.raise_for_status(); d=r.json()
    if "error" in d: raise RuntimeError(d["error"])
    d["total_time_ms"]=ms; d["file_size_actual"]=sz; return d

def call_pdf_ocr(path, url):
    """PDF → Image → Tesseract OCR pipeline."""
    fn = os.path.basename(path); b64 = encode(path); sz = os.path.getsize(path)
    t=time.time(); r=requests.post(url,json={"pdf":b64,"filename":fn},timeout=300)
    ms=round((time.time()-t)*1000,2); r.raise_for_status(); d=r.json()
    if "error" in d: raise RuntimeError(d["error"])
    d["total_time_ms"]=ms; d["file_size_actual"]=sz; return d

def main():
    ap = argparse.ArgumentParser(description="OCR/PDF CLI — Extract text from images and PDFs")
    ap.add_argument("files", nargs="+", help="Image or PDF file(s)")
    ap.add_argument("--url", default="http://localhost:8080", help="Base URL (default: http://localhost:8080)")
    ap.add_argument("--direct", action="store_true", help="Bypass nginx, call :9000 directly")
    ap.add_argument("--pdf-ocr", action="store_true", help="Use PDF→Image→OCR pipeline for PDFs (slower, works on scanned docs)")
    ap.add_argument("--no-header", action="store_true", help="Omit CSV header row")
    ap.add_argument("-o","--output", help="Write CSV to file")
    a = ap.parse_args()

    fields = ["filename","type","method","file_size","total_ms","processing_ms","img_extract_ms","ocr_ms","pages","words","chars","text"]
    out = open(a.output,"w",newline="",encoding="utf-8") if a.output else sys.stdout
    w = csv.DictWriter(out, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
    if not a.no_header: w.writeheader()

    errs = 0
    for fp in a.files:
        if not os.path.isfile(fp): print(f"  ✗ Not found: {fp}",file=sys.stderr); errs+=1; continue
        ext = os.path.splitext(fp)[1].lower()
        try:
            if ext in PDF_EXTS and a.pdf_ocr:
                # ── PDF → Image → OCR ──
                url = "http://localhost:9000/2015-03-31/functions/pdf-ocr/invocations" if a.direct else f"{a.url}/api/pdf-ocr"
                d = call_pdf_ocr(fp, url)
                t = d.get("timing",{})
                w.writerow({
                    "filename":d.get("filename",""), "type":"pdf", "method":"pdf-ocr",
                    "file_size":d.get("file_size_actual",""),
                    "total_ms":d.get("total_time_ms",""),
                    "processing_ms":t.get("pipeline_ms",""),
                    "img_extract_ms":t.get("total_image_extract_ms",""),
                    "ocr_ms":t.get("total_ocr_ms",""),
                    "pages":d.get("page_count",""),
                    "words":d.get("total_word_count",0),
                    "chars":d.get("total_char_count",0),
                    "text":d.get("text","").replace("\n","\\n"),
                })
                print(f"  ✓ {os.path.basename(fp)} [pdf-ocr] — {d.get('page_count','?')}pg, {d.get('total_word_count',0)}w, pipeline {t.get('pipeline_ms','?')}ms (extract {t.get('total_image_extract_ms','?')}ms + ocr {t.get('total_ocr_ms','?')}ms), round-trip {d.get('total_time_ms','?')}ms", file=sys.stderr)
                for p in d.get("pages",[]):
                    print(f"      Page {p['page']}: extract={p['image_extract_ms']}ms  ocr={p['ocr_ms']}ms  words={p['word_count']}  img={p['image_size_bytes']}B", file=sys.stderr)

            elif ext in PDF_EXTS:
                # ── PDF direct text extract (no OCR) ──
                url = "http://localhost:9000/2015-03-31/functions/pdf-extract/invocations" if a.direct else f"{a.url}/api/pdf"
                d = call_pdf_text(fp, url)
                w.writerow({
                    "filename":d.get("filename",""), "type":"pdf", "method":"pdf-text",
                    "file_size":d.get("file_size_actual",d.get("file_size_bytes","")),
                    "total_ms":d.get("total_time_ms",""),
                    "processing_ms":d.get("processing_time_ms",""),
                    "img_extract_ms":"", "ocr_ms":"",
                    "pages":d.get("page_count",""),
                    "words":d.get("total_word_count",0),
                    "chars":d.get("total_char_count",0),
                    "text":d.get("text","").replace("\n","\\n"),
                })
                print(f"  ✓ {os.path.basename(fp)} [pdf-text] — {d.get('page_count','?')}pg, {d.get('total_word_count',0)}w, extract {d.get('processing_time_ms','?')}ms, round-trip {d.get('total_time_ms','?')}ms", file=sys.stderr)
                for p in d.get("pages",[]):
                    print(f"      Page {p['page']}: {p['extraction_time_ms']}ms  {p['word_count']}w  {p['char_count']}ch", file=sys.stderr)

            elif ext in IMG_EXTS:
                # ── Image OCR ──
                url = "http://localhost:9000/2015-03-31/functions/ocr-service/invocations" if a.direct else f"{a.url}/api/ocr"
                d = call_img_ocr(fp, url)
                w.writerow({
                    "filename":d.get("filename",""), "type":"image", "method":"image-ocr",
                    "file_size":d.get("file_size_bytes",""),
                    "total_ms":d.get("total_time_ms",""),
                    "processing_ms":"", "img_extract_ms":"",
                    "ocr_ms":d.get("processing_time_ms",""),
                    "pages":1, "words":d.get("word_count",0),
                    "chars":d.get("text_length",0),
                    "text":d.get("text","").replace("\n","\\n"),
                })
                print(f"  ✓ {os.path.basename(fp)} [image-ocr] — {d['word_count']}w, ocr {d['processing_time_ms']}ms, round-trip {d['total_time_ms']}ms", file=sys.stderr)
            else:
                print(f"  ✗ Unsupported: {fp}",file=sys.stderr); errs+=1; continue
            out.flush()
        except Exception as e:
            print(f"  ✗ {fp}: {e}",file=sys.stderr); errs+=1

    if a.output: out.close(); print(f"\nSaved to {a.output}",file=sys.stderr)
    print(f"\nProcessed {len(a.files)-errs}/{len(a.files)} files",file=sys.stderr)
    sys.exit(1 if errs else 0)

if __name__ == "__main__": main()
