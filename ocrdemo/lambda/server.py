"""
Lambda-compatible invoke server.
Accepts POST requests on the same endpoint LocalStack uses:
  POST /2015-03-31/functions/{function_name}/invocations

This lets the frontend and nginx config work identically to a real
LocalStack Lambda setup.
"""

from flask import Flask, request, jsonify
import json
from handler import lambda_handler

app = Flask(__name__)


@app.route("/2015-03-31/functions/<function_name>/invocations", methods=["POST"])
def invoke(function_name):
    """Mimics the Lambda Invoke API."""
    try:
        event = request.get_json(force=True)
        result = lambda_handler(event, None)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "lambda-ocr"}), 200


if __name__ == "__main__":
    print("=" * 50)
    print("  OCR Lambda Service running on :9000")
    print("  POST /2015-03-31/functions/ocr-service/invocations")
    print("=" * 50)
    app.run(host="0.0.0.0", port=9000)
