"""
Backend API — upload → invoke LocalStack Lambda → return text + timing.
"""
import os, json, time, base64, logging
import boto3
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ENDPOINT  = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
FUNC_NAME = os.environ.get("LAMBDA_FUNCTION_NAME", "ocr-extract")
REGION    = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
ALLOWED   = {"pdf", "tiff", "tif", "png", "jpg", "jpeg"}
MAX_SIZE  = 20 * 1024 * 1024

def _client():
    return boto3.client("lambda", endpoint_url=ENDPOINT, region_name=REGION,
                        aws_access_key_id="test", aws_secret_access_key="test")

def _wait_active(timeout=180):
    c = _client()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            cfg = c.get_function(FunctionName=FUNC_NAME).get("Configuration", {})
            state = cfg.get("State", "Unknown")
            if state == "Active":
                return True
            if state == "Failed":
                log.error("Lambda Failed: %s", cfg.get("StateReasonCode"))
                return False
            log.info("Lambda state: %s — waiting...", state)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                log.info("Lambda '%s' not found yet...", FUNC_NAME)
        except Exception as e:
            log.warning("Connection error: %s", e)
        time.sleep(5)
    return False

with app.app_context():
    log.info("Waiting for Lambda '%s'...", FUNC_NAME)
    if _wait_active():
        log.info("✓ Lambda '%s' Active!", FUNC_NAME)
    else:
        log.error("✗ Lambda '%s' not Active", FUNC_NAME)

@app.route("/api/extract", methods=["POST"])
def extract_text():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED:
        return jsonify({"error": "Unsupported type. Allowed: %s" % ", ".join(sorted(ALLOWED))}), 400
    data = f.read()
    if len(data) > MAX_SIZE:
        return jsonify({"error": "File exceeds 20 MB"}), 413

    payload = json.dumps({
        "file_data": base64.b64encode(data).decode(),
        "file_name": f.filename,
        "file_type": ext,
    })
    log.info("Invoking '%s' for '%s' (%d bytes)", FUNC_NAME, f.filename, len(data))
    t0 = time.perf_counter()
    try:
        c = _client()
        try:
            cfg = c.get_function(FunctionName=FUNC_NAME).get("Configuration", {})
            state = cfg.get("State", "Unknown")
            if state != "Active":
                return jsonify({"error": "Lambda state='%s'. Wait for deployment." % state}), 503
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                funcs = [fn["FunctionName"] for fn in c.list_functions().get("Functions", [])]
                return jsonify({"error": "Lambda '%s' not found. Available: %s" % (FUNC_NAME, funcs)}), 503
            raise

        resp = c.invoke(FunctionName=FUNC_NAME, InvocationType="RequestResponse", Payload=payload)
        raw = resp["Payload"].read().decode()
        elapsed = round((time.perf_counter() - t0) * 1000)

        if "FunctionError" in resp:
            log.error("FunctionError: %s", raw[:500])
            return jsonify({"error": "Lambda error: %s" % raw[:500]}), 502

        result = json.loads(raw)
        body = json.loads(result["body"]) if isinstance(result.get("body"), str) else result.get("body", result)
        if result.get("statusCode", 200) >= 400:
            return jsonify({"error": body.get("error", "Extraction failed")}), 502

        return jsonify({
            "text": body.get("text", ""),
            "pages": body.get("pages"),
            "processing_time_ms": body.get("processing_time_ms", elapsed),
        })
    except ClientError as e:
        log.exception("AWS error")
        return jsonify({"error": "AWS: %s" % e.response["Error"]["Message"]}), 502
    except Exception as e:
        log.exception("Failed")
        return jsonify({"error": str(e)}), 502

@app.route("/api/health", methods=["GET"])
def health():
    try:
        c = _client()
        cfg = c.get_function(FunctionName=FUNC_NAME).get("Configuration", {})
        return jsonify({"status": "ok", "lambda_state": cfg.get("State"),
                        "runtime": cfg.get("Runtime"), "function": FUNC_NAME,
                        "layers": [l.get("Arn","") for l in cfg.get("Layers", [])]})
    except Exception as e:
        return jsonify({"status": "ok", "lambda_state": "not_found", "error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
