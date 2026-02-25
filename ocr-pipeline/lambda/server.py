"""
Lambda-compatible invoke server.
Routes:
  POST /2015-03-31/functions/ocr-service/invocations    → Image OCR (Tesseract)
  POST /2015-03-31/functions/pdf-extract/invocations     → PDF direct text extraction
  POST /2015-03-31/functions/pdf-ocr/invocations         → PDF → Image → OCR pipeline
"""

from flask import Flask, request, jsonify
from handler import lambda_handler
from pdf_handler import pdf_handler
from pdf_ocr_handler import pdf_ocr_handler

app = Flask(__name__)

HANDLERS = {
    "ocr-service": lambda_handler,
    "pdf-extract": pdf_handler,
    "pdf-ocr": pdf_ocr_handler,
}


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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "services": list(HANDLERS.keys())}), 200


if __name__ == "__main__":
    print("=" * 60)
    print("  Lambda Service running on :9000")
    print("  POST .../functions/ocr-service/invocations   (images)")
    print("  POST .../functions/pdf-extract/invocations    (PDF text)")
    print("  POST .../functions/pdf-ocr/invocations        (PDF→OCR)")
    print("=" * 60)
    app.run(host="0.0.0.0", port=9000)
