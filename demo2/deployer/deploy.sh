#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  Deployer: publishes Tesseract Lambda Layer, creates function
#  with python3.9 runtime (Amazon Linux 2 — matches the layer),
#  waits for Active state.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

FUNCTION_NAME="ocr-extract"
LAYER_NAME="tesseract-layer"
LAYER_ZIP="/layers/layer.zip"
ENDPOINT="http://localstack:4566"
REGION="us-east-1"
ROLE_ARN="arn:aws:iam::000000000000:role/lambda-ocr-role"
# IMPORTANT: python3.9 runs on Amazon Linux 2 — same OS the layer was built on
RUNTIME="python3.9"

export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=$REGION

awsl() { aws --endpoint-url="$ENDPOINT" --region "$REGION" "$@"; }

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  OCR Lambda Deployer                             ║"
echo "╚══════════════════════════════════════════════════╝"

# ── 1. Wait for layer.zip ──
echo "→ [1/7] Waiting for layer zip..."
for i in $(seq 1 180); do
    [ -f "$LAYER_ZIP" ] && break
    [ "$i" -eq 180 ] && { echo "✗ layer.zip not found after 3min"; exit 1; }
    sleep 1
done
echo "  ✓ Found: $(du -sh $LAYER_ZIP | cut -f1)"

# ── 2. Build function zip ──
echo "→ [2/7] Building function zip..."
mkdir -p /tmp/fn
pip install --quiet --no-cache-dir -t /tmp/fn \
    PyPDF2==3.0.1 \
    pytesseract==0.3.10 \
    Pillow==10.3.0 \
    pdf2image==1.17.0 \
    typing_extensions>=4.0
cp /src/handler.py /tmp/fn/
cd /tmp/fn && zip -r9 /tmp/function.zip . > /dev/null 2>&1
echo "  ✓ Function zip: $(du -sh /tmp/function.zip | cut -f1)"

# ── 3. Wait for Lambda service ──
echo "→ [3/7] Waiting for LocalStack Lambda service..."
for i in $(seq 1 60); do
    STATUS=$(curl -sf "$ENDPOINT/_localstack/health" 2>/dev/null \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('services',{}).get('lambda','?'))" 2>/dev/null || echo "?")
    if [ "$STATUS" = "running" ] || [ "$STATUS" = "available" ]; then
        echo "  ✓ Lambda service: $STATUS"; break
    fi
    echo "  ... $STATUS ($i/60)"
    sleep 2
done

# ── 4. Create IAM role ──
echo "→ [4/7] Creating IAM role..."
awsl iam create-role \
    --role-name lambda-ocr-role \
    --assume-role-policy-document '{
        "Version":"2012-10-17",
        "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
    }' > /dev/null 2>&1 || echo "  (exists)"

# ── 5. Publish Layer ──
echo "→ [5/7] Publishing Lambda Layer..."
LAYER_OUT=$(awsl lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "Tesseract OCR + Poppler (built on Amazon Linux 2)" \
    --zip-file "fileb://${LAYER_ZIP}" \
    --compatible-runtimes python3.9 \
    --output json)
LAYER_ARN=$(echo "$LAYER_OUT" | python3 -c "import sys,json;print(json.load(sys.stdin)['LayerVersionArn'])")
echo "  ✓ $LAYER_ARN"

# ── 6. Create function ──
echo "→ [6/7] Creating Lambda function..."
awsl lambda delete-function --function-name "$FUNCTION_NAME" 2>/dev/null || true
sleep 2

CREATE_OUT=$(awsl lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime "$RUNTIME" \
    --role "$ROLE_ARN" \
    --handler handler.handler \
    --zip-file fileb:///tmp/function.zip \
    --timeout 120 \
    --memory-size 1024 \
    --layers "$LAYER_ARN" \
    --environment "Variables={TESSDATA_PREFIX=/opt/share/tessdata,PATH=/opt/bin:/var/lang/bin:/usr/local/bin:/usr/bin:/bin,LD_LIBRARY_PATH=/opt/lib:/var/lang/lib:/lib64:/usr/lib64}" \
    --output json)

echo "$CREATE_OUT" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f\"  Name:    {d.get('FunctionName')}\")
print(f\"  Runtime: {d.get('Runtime')}\")
print(f\"  State:   {d.get('State','?')}\")
print(f\"  Layers:  {[l['Arn'] for l in d.get('Layers',[])]}\")
"

# ── 7. Wait for Active ──
echo "→ [7/7] Waiting for Active state..."
for i in $(seq 1 90); do
    STATE=$(awsl lambda get-function --function-name "$FUNCTION_NAME" \
        --query 'Configuration.State' --output text 2>/dev/null || echo "NOT_FOUND")
    if [ "$STATE" = "Active" ]; then
        echo "  ✓ Function is Active!"; break
    fi
    if [ "$STATE" = "Failed" ]; then
        echo "  ✗ FAILED"; awsl lambda get-function --function-name "$FUNCTION_NAME" --output json; exit 1
    fi
    echo "  State=$STATE ($i/90)"
    [ "$i" -eq 90 ] && { echo "✗ Timed out"; exit 1; }
    sleep 2
done

# ── Verify ──
echo ""
echo "→ Functions:"
awsl lambda list-functions --query 'Functions[].{Name:FunctionName,State:State,Runtime:Runtime}' --output table 2>/dev/null || true
echo ""
echo "→ Layers:"
awsl lambda list-layers --output table 2>/dev/null || true

# ── Test invocation ──
echo ""
echo "→ Test invoke..."
awsl lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload '{"file_data":"dGVzdA==","file_type":"png","file_name":"test.png"}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/test.json 2>&1 || true
echo "  Response: $(cat /tmp/test.json 2>/dev/null | head -c 300)"

echo ""
echo "════════════════════════════════════════════════════"
echo "  ✓ OCR Stack Ready!"
echo "  Frontend:   http://localhost:8080"
echo "  Backend:    http://localhost:5000/api/health"
echo "  LocalStack: http://localhost:4566"
echo "════════════════════════════════════════════════════"
