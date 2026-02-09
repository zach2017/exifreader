#!/bin/bash
set -euo pipefail

FUNCTION_NAME="ocr-extract"
LAYER_ZIP="/layers/layer.zip"
ENDPOINT="http://localstack:4566"
REGION="us-east-1"
ROLE_ARN="arn:aws:iam::000000000000:role/lambda-ocr-role"
RUNTIME="python3.9"

export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=$REGION

awsl() { aws --endpoint-url="$ENDPOINT" --region "$REGION" "$@"; }

echo ""
echo "========================================"
echo "  OCR Lambda Deployer"
echo "========================================"

echo "[1/6] Waiting for layer zip..."
TRIES=0
while [ ! -f "$LAYER_ZIP" ]; do
    TRIES=$((TRIES + 1))
    if [ "$TRIES" -ge 180 ]; then
        echo "FAIL: layer.zip not found"
        exit 1
    fi
    sleep 1
done
echo "  Found layer zip"

echo "[2/6] Building combined function zip..."
# Strategy: merge tesseract binaries + python code into ONE zip.
# The zip extracts to /var/task/ in the Lambda container.
# So bin/tesseract becomes /var/task/bin/tesseract etc.
BUILD_DIR="/tmp/build"
mkdir -p "$BUILD_DIR"

# Unpack tesseract binaries (bin/, lib/, share/) into build dir
cd "$BUILD_DIR"
unzip -qo "$LAYER_ZIP"
echo "  Unpacked layer: $(ls)"

# Make binaries executable
chmod +x "$BUILD_DIR/bin/"* 2>/dev/null || true

# Install PyPDF2 (pure Python, only pip dependency)
pip3 install --no-cache-dir --target "$BUILD_DIR" 'PyPDF2==3.0.1'

# Copy handler
cp /src/handler.py "$BUILD_DIR/"

# Create the combined zip
cd "$BUILD_DIR"
zip -r9 /tmp/function.zip . > /dev/null 2>&1
ZIP_SIZE=$(du -sh /tmp/function.zip | cut -f1)
echo "  Combined zip: $ZIP_SIZE"
echo "  Contents: handler.py + PyPDF2 + bin/ + lib/ + share/"

echo "[3/6] Waiting for Lambda service..."
TRIES=0
while true; do
    TRIES=$((TRIES + 1))
    HEALTH=$(curl -sf "$ENDPOINT/_localstack/health" 2>/dev/null || echo '{}')
    STATUS=$(echo "$HEALTH" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("services",{}).get("lambda","unknown"))' 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "running" ] || [ "$STATUS" = "available" ]; then
        echo "  Lambda service ready"
        break
    fi
    if [ "$TRIES" -ge 60 ]; then
        echo "  Timeout, continuing anyway"
        break
    fi
    sleep 2
done

echo "[4/6] Creating IAM role..."
awsl iam create-role \
    --role-name lambda-ocr-role \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
    > /dev/null 2>&1 || echo "  (exists)"

echo "[5/6] Creating function (no layers - binaries bundled in zip)..."
awsl lambda delete-function --function-name "$FUNCTION_NAME" 2>/dev/null || true
sleep 2

awsl lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime "$RUNTIME" \
    --role "$ROLE_ARN" \
    --handler handler.handler \
    --zip-file fileb:///tmp/function.zip \
    --timeout 120 \
    --memory-size 1024 \
    --environment '{"Variables":{"TESSDATA_PREFIX":"/var/task/share/tessdata","LD_LIBRARY_PATH":"/var/task/lib:/var/lang/lib:/lib64:/usr/lib64"}}' \
    --query 'FunctionName' \
    --output text
echo "  Created"

echo "[6/6] Waiting for Active..."
TRIES=0
while true; do
    TRIES=$((TRIES + 1))
    STATE=$(awsl lambda get-function --function-name "$FUNCTION_NAME" \
        --query 'Configuration.State' --output text 2>/dev/null || echo "NOT_FOUND")
    if [ "$STATE" = "Active" ]; then
        echo "  Active!"
        break
    fi
    if [ "$STATE" = "Failed" ]; then
        echo "  FAILED"
        exit 1
    fi
    if [ "$TRIES" -ge 90 ]; then
        echo "  Timed out"
        exit 1
    fi
    echo "  state=$STATE ($TRIES/90)"
    sleep 2
done

echo ""
echo "Test invoke..."
awsl lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{"file_data":"dGVzdA==","file_type":"png","file_name":"test.png"}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/test.json 2>&1 || true
cat /tmp/test.json 2>/dev/null || true
echo ""

echo ""
echo "========================================"
echo "  OCR Stack Ready!"
echo "  Frontend:   http://localhost:8080"
echo "  Backend:    http://localhost:5000"
echo "  LocalStack: http://localhost:4566"
echo "========================================"
