import io
import os
from flask import Flask, request, send_file, send_from_directory, jsonify
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image

app = Flask(__name__, static_folder="static", static_url_path="")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def make_image_overlay_pdf(image_bytes, page_w, page_h, placement="top-right"):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    target_w = page_w * 0.30
    scale = target_w / img.width
    target_h = img.height * scale

    if target_h > page_h * 0.35:
        scale = (page_h * 0.35) / img.height
        target_w = img.width * scale
        target_h = img.height * scale

    margin = 18
    if placement == "top-left":
        x, y = margin, page_h - margin - target_h
    elif placement == "bottom-left":
        x, y = margin, margin
    elif placement == "bottom-right":
        x, y = page_w - margin - target_w, margin
    else:
        x, y = page_w - margin - target_w, page_h - margin - target_h

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.drawImage(ImageReader(img), x, y, width=target_w, height=target_h, mask="auto")
    c.showPage()
    c.save()
    return buf.getvalue()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/embed")
def embed():
    if "pdf" not in request.files or "extra" not in request.files:
        return jsonify({"error": "Missing files"}), 400

    pdf_bytes = request.files["pdf"].read()
    extra_file = request.files["extra"]
    extra_bytes = extra_file.read()
    extra_name = extra_file.filename or "attachment.bin"

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for p in reader.pages:
        writer.add_page(p)

    # always embed file as attachment
    try:
        writer.add_attachment(extra_name, extra_bytes)
    except Exception:
        pass

    # if image also overlay on first page
    if extra_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        first = writer.pages[0]
        w, h = float(first.mediabox.width), float(first.mediabox.height)

        overlay_pdf = make_image_overlay_pdf(extra_bytes, w, h)
        overlay_reader = PdfReader(io.BytesIO(overlay_pdf))
        first.merge_page(overlay_reader.pages[0])

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)

    return send_file(
        out,
        as_attachment=True,
        download_name="updated.pdf",
        mimetype="application/pdf"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)