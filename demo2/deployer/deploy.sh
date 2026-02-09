#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  Deployer: builds Lambda zip, deploys to LocalStack, waits
#  for the function to reach Active state before exiting.
# ──────────────────────────────────────────────────────────────
set -euo pipefail

FUNCTION_NAME="ocr-extract"
ENDPOINT="http://localstack:4566"
REGION="us-east-1"
ROLE_ARN="arn:aws:iam::000000000000:role/lambda-ocr-role"

export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=$REGION

alias aws="aws --endpoint-url=$ENDPOINT --region $REGION"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  OCR Lambda Deployer                             ║"
echo "╚══════════════════════════════════════════════════╝"

# ── 1. Build Lambda zip ──
echo "→ [1/5] Building Lambda deployment zip..."
mkdir -p /tmp/pkg
pip install --quiet --no-cache-dir -t /tmp/pkg \
    PyPDF2==3.0.1 \
    pytesseract==0.3.10 \
    Pillow==10.3.0 \
    pdf2image==1.17.0
cp /src/handler.py /tmp/pkg/
cd /tmp/pkg
zip -r9 /tmp/lambda.zip . > /dev/null 2>&1
echo "  ✓ Zip size: $(du -sh /tmp/lambda.zip | cut -f1)"

# ── 2. Wait for LocalStack ──
echo "→ [2/5] Waiting for LocalStack..."
for i in $(seq 1 60); do
    if curl -sf "$ENDPOINT/_localstack/health" > /dev/null 2>&1; then
        echo "  ✓ LocalStack is up"
        break
    fi
    [ "$i" -eq 60 ] && { echo "✗ LocalStack not reachable after 60s"; exit 1; }
    sleep 2
done

# Wait specifically for Lambda service
echo "  Waiting for Lambda service..."
for i in $(seq 1 30); do
    HEALTH=$(curl -sf "$ENDPOINT/_localstack/health" 2>/dev/null || echo "{}")
    LAMBDA_STATUS=$(echo "$HEALTH" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('services',{}).get('lambda','unknown'))
except: print('unknown')
" 2>/dev/null)
    if [ "$LAMBDA_STATUS" = "running" ] || [ "$LAMBDA_STATUS" = "available" ]; then
        echo "  ✓ Lambda service status: $LAMBDA_STATUS"
        break
    fi
    echo "  Lambda service: $LAMBDA_STATUS (attempt $i/30)"
    [ "$i" -eq 30 ] && { echo "⚠ Lambda service not 'running' but continuing..."; }
    sleep 3
done

# ── 3. Create IAM role ──
echo "→ [3/5] Creating IAM role..."
aws --endpoint-url=$ENDPOINT iam create-role \
    --role-name lambda-ocr-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }' > /dev/null 2>&1 || echo "  (role already exists)"

# ── 4. Deploy Lambda ──
echo "→ [4/5] Deploying Lambda function..."

# Delete old version if exists
aws --endpoint-url=$ENDPOINT lambda delete-function \
    --function-name "$FUNCTION_NAME" 2>/dev/null || true
sleep 2

# Create function
echo "  Creating function '$FUNCTION_NAME'..."
aws --endpoint-url=$ENDPOINT lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.11 \
    --role "$ROLE_ARN" \
    --handler handler.handler \
    --zip-file fileb:///tmp/lambda.zip \
    --timeout 120 \
    --memory-size 1024 \
    --output json | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  FunctionName: {d.get('FunctionName')}\" )
print(f\"  FunctionArn:  {d.get('FunctionArn')}\" )
print(f\"  State:        {d.get('State','N/A')}\" )
print(f\"  Runtime:      {d.get('Runtime')}\" )
"

# ── 5. Wait for Active state ──
# LocalStack 3.x creates functions asynchronously (Pending → Active)
echo "→ [5/5] Waiting for function to become Active..."
for i in $(seq 1 60); do
    STATE=$(aws --endpoint-url=$ENDPOINT lambda get-function \
        --function-name "$FUNCTION_NAME" \
        --query 'Configuration.State' \
        --output text 2>/dev/null || echo "NOT_FOUND")

    LAST_STATUS=$(aws --endpoint-url=$ENDPOINT lambda get-function \
        --function-name "$FUNCTION_NAME" \
        --query 'Configuration.LastUpdateStatus' \
        --output text 2>/dev/null || echo "UNKNOWN")

    echo "  State=$STATE  LastUpdateStatus=$LAST_STATUS  (attempt $i/60)"

    if [ "$STATE" = "Active" ]; then
        echo "  ✓ Function is Active!"
        break
    fi
    if [ "$STATE" = "Failed" ]; then
        REASON=$(aws --endpoint-url=$ENDPOINT lambda get-function \
            --function-name "$FUNCTION_NAME" \
            --query 'Configuration.StateReasonCode' \
            --output text 2>/dev/null || echo "unknown")
        echo "  ✗ Function creation FAILED: $REASON"
        exit 1
    fi
    [ "$i" -eq 60 ] && { echo "✗ Timed out waiting for Active state"; exit 1; }
    sleep 3
done

# ── Verify: list all functions ──
echo ""
echo "→ Deployed functions:"
aws --endpoint-url=$ENDPOINT lambda list-functions \
    --query 'Functions[].{Name:FunctionName, State:State, Runtime:Runtime}' \
    --output table 2>/dev/null || \
aws --endpoint-url=$ENDPOINT lambda list-functions --output json

# ── Quick test invocation ──
echo ""
echo "→ Test invocation..."
# Base64 of "test"
TEST_PAYLOAD='{"file_data":"dGVzdA==","file_type":"png","file_name":"test.png"}'
RESPONSE=$(aws --endpoint-url=$ENDPOINT lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --payload "$TEST_PAYLOAD" \
    --cli-binary-format raw-in-base64-out \
    /tmp/test-response.json 2>&1) || true
echo "  Invoke result: $RESPONSE"
echo "  Response body: $(cat /tmp/test-response.json 2>/dev/null | head -c 200)"

echo ""
echo "════════════════════════════════════════════════════"
echo "  ✓ OCR Stack Ready!"
echo ""
echo "  Frontend:   http://localhost:8080"
echo "  Backend:    http://localhost:5000/api/health"
echo "  LocalStack: http://localhost:4566"
echo "════════════════════════════════════════════════════"
