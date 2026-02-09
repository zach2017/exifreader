import os
import json
import time
import base64
import logging

import boto3
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
FUNC_NAME = os.environ.get("LAMBDA_FUNCTION_NAME", "ocr-extract")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
ALLOWED = set(["pdf", "tiff", "tif", "png", "jpg", "jpeg"])
MAX_SIZE = 20 * 1024 * 1024


def get_client():
    return boto3.client(
        "lambda",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def wait_for_active(timeout=180):
    c = get_client()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = c.get_function(FunctionName=FUNC_NAME)
            state = resp.get("Configuration", {}).get("State", "Unknown")
            if state == "Active":
                return True
            if state == "Failed":
                log.error("Lambda state Failed")
                return False
            log.info("Lambda state: %s", state)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                log.info("Lambda not found yet")
            else:
                log.warning("ClientError: %s", str(e))
        except Exception as e:
            log.warning("Connection error: %s", str(e))
        time.sleep(5)
    return False


with app.app_context():
    log.info("Waiting for Lambda to become Active...")
    if wait_for_active():
        log.info("Lambda is Active")
    else:
        log.error("Lambda did not become Active")


@app.route("/api/extract", methods=["POST"])
def extract_text():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = ""
    if "." in f.filename:
        ext = f.filename.rsplit(".", 1)[1].lower()

    if ext not in ALLOWED:
        return jsonify({"error": "Unsupported file type"}), 400

    data = f.read()
    if len(data) > MAX_SIZE:
        return jsonify({"error": "File exceeds 20 MB"}), 413

    payload = json.dumps({
        "file_data": base64.b64encode(data).decode("ascii"),
        "file_name": f.filename,
        "file_type": ext,
    })

    log.info("Invoking Lambda for %s (%d bytes)", f.filename, len(data))
    t0 = time.perf_counter()

    try:
        c = get_client()

        try:
            info = c.get_function(FunctionName=FUNC_NAME)
            state = info.get("Configuration", {}).get("State", "Unknown")
            if state != "Active":
                return jsonify({"error": "Lambda not ready, state=" + state}), 503
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                return jsonify({"error": "Lambda function not found"}), 503
            raise

        resp = c.invoke(
            FunctionName=FUNC_NAME,
            InvocationType="RequestResponse",
            Payload=payload,
        )
        raw = resp["Payload"].read().decode("utf-8")
        elapsed = int((time.perf_counter() - t0) * 1000)

        if "FunctionError" in resp:
            log.error("FunctionError: %s", raw[:500])
            return jsonify({"error": "Lambda error: " + raw[:300]}), 502

        result = json.loads(raw)

        body = result
        if "body" in result and isinstance(result["body"], str):
            body = json.loads(result["body"])
        elif "body" in result:
            body = result["body"]

        sc = result.get("statusCode", 200)
        if sc >= 400:
            return jsonify({"error": body.get("error", "Extraction failed")}), 502

        return jsonify({
            "text": body.get("text", ""),
            "pages": body.get("pages"),
            "processing_time_ms": body.get("processing_time_ms", elapsed),
        })

    except ClientError as e:
        log.exception("AWS error")
        return jsonify({"error": "AWS error: " + str(e)}), 502
    except Exception as e:
        log.exception("Unexpected error")
        return jsonify({"error": str(e)}), 502


@app.route("/api/health", methods=["GET"])
def health():
    try:
        c = get_client()
        info = c.get_function(FunctionName=FUNC_NAME)
        conf = info.get("Configuration", {})
        layers = []
        for layer in conf.get("Layers", []):
            layers.append(layer.get("Arn", ""))
        return jsonify({
            "status": "ok",
            "lambda_state": conf.get("State"),
            "runtime": conf.get("Runtime"),
            "function": FUNC_NAME,
            "layers": layers,
        })
    except Exception as e:
        return jsonify({
            "status": "ok",
            "lambda_state": "not_found",
            "error": str(e),
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
