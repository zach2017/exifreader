#!/bin/bash
# ══════════════════════════════════════════════
#  LocalStack Bootstrap
#  Creates: S3 bucket + Lambda function + S3→Lambda trigger
#
#  This script runs INSIDE the LocalStack container
#  after all services are healthy (ready.d hook).
# ══════════════════════════════════════════════
set -eo pipefail

REGION="${AWS_REGION:-us-east-1}"
BUCKET="${S3_BUCKET:-ocr-documents}"
API_URL="${API_BASE_URL:-http://api-server:8000}"
FUNC_NAME="ocr-trigger"

echo "════════════════════════════════════════════"
echo "  LocalStack Init"
echo "════════════════════════════════════════════"

# ── 1. Verify services are ready ─────────────
echo ""
echo "⏳ [1/5] Verifying LocalStack services..."
MAX_WAIT=30
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTH=$(curl -sf http://localhost:4566/_localstack/health 2>/dev/null || echo "{}")
    S3_OK=$(echo "$HEALTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
s = d.get('services',{})
print('yes' if s.get('s3') in ('running','available','ready') and s.get('lambda') in ('running','available','ready') else 'no')
" 2>/dev/null || echo "no")

    if [ "$S3_OK" = "yes" ]; then
        echo "   ✓ S3 and Lambda services ready"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo "   ↳ waiting... (${WAITED}s)"
done

# Also verify the API server is reachable from inside LocalStack
echo "   ↳ Checking API server at ${API_URL}..."
API_WAIT=0
while [ $API_WAIT -lt 30 ]; do
    if curl -sf "${API_URL}/health" > /dev/null 2>&1; then
        echo "   ✓ API server reachable"
        break
    fi
    sleep 2
    API_WAIT=$((API_WAIT + 2))
    echo "   ↳ API not ready yet (${API_WAIT}s)"
done

if ! curl -sf "${API_URL}/health" > /dev/null 2>&1; then
    echo "   ⚠ WARNING: API server not reachable at ${API_URL}"
    echo "     Lambda invocations may fail until API is available."
fi

# ── 2. Create + verify S3 Bucket ─────────────
echo ""
echo "📦 [2/5] Creating S3 bucket: ${BUCKET}"

if awslocal s3api head-bucket --bucket "${BUCKET}" --region "${REGION}" 2>/dev/null; then
    echo "   ✓ Bucket already exists"
else
    if [ "${REGION}" = "us-east-1" ]; then
        awslocal s3api create-bucket \
            --bucket "${BUCKET}" \
            --region "${REGION}"
    else
        awslocal s3api create-bucket \
            --bucket "${BUCKET}" \
            --region "${REGION}" \
            --create-bucket-configuration LocationConstraint="${REGION}"
    fi
    echo "   ✓ Bucket created"
fi

# Read/write verification
echo "   ↳ Running read/write test..."
echo "init-test-ok" | awslocal s3 cp - "s3://${BUCKET}/__test/verify.txt" --region "${REGION}"
VERIFY=$(awslocal s3 cp "s3://${BUCKET}/__test/verify.txt" - --region "${REGION}")
awslocal s3 rm "s3://${BUCKET}/__test/verify.txt" --region "${REGION}"
if [ "$VERIFY" = "init-test-ok" ]; then
    echo "   ✓ Read/write verified"
else
    echo "   ✗ Read/write FAILED — got: '${VERIFY}'"
    exit 1
fi

# ── 3. Package Lambda ────────────────────────
echo ""
echo "📋 [3/5] Packaging Lambda function"

if [ ! -f /opt/lambda/handler.py ]; then
    echo "   ✗ ERROR: /opt/lambda/handler.py not found!"
    exit 1
fi

rm -f /tmp/lambda.zip
cd /tmp && zip -j /tmp/lambda.zip /opt/lambda/handler.py
ZIP_SIZE=$(wc -c < /tmp/lambda.zip)
echo "   ✓ lambda.zip (${ZIP_SIZE} bytes)"

# ── 4. Create Lambda function ────────────────
echo ""
echo "🔧 [4/5] Creating Lambda function: ${FUNC_NAME}"

# Delete if exists (idempotent)
awslocal lambda delete-function \
    --function-name "${FUNC_NAME}" \
    --region "${REGION}" 2>/dev/null || true
sleep 2

awslocal lambda create-function \
    --function-name "${FUNC_NAME}" \
    --runtime python3.12 \
    --handler handler.handler \
    --zip-file fileb:///tmp/lambda.zip \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --timeout 300 \
    --memory-size 256 \
    --environment "Variables={API_BASE_URL=${API_URL},AWS_REGION=${REGION}}" \
    --region "${REGION}"

echo "   ✓ Function created"

# Wait for Active state — this is critical for docker-based execution.
# LocalStack needs time to pull/prepare the Lambda runtime Docker image.
echo "   ↳ Waiting for Active state..."
MAX_WAIT=120
WAITED=0
STATE="Pending"
while [ $WAITED -lt $MAX_WAIT ]; do
    STATE=$(awslocal lambda get-function \
        --function-name "${FUNC_NAME}" \
        --region "${REGION}" \
        --query 'Configuration.State' \
        --output text 2>/dev/null || echo "Unknown")

    if [ "$STATE" = "Active" ] || [ "$STATE" = "active" ]; then
        echo "   ✓ Lambda Active"
        break
    fi
    sleep 3
    WAITED=$((WAITED + 3))
    echo "   ↳ state=${STATE} (${WAITED}s)"
done

if [ "$STATE" != "Active" ] && [ "$STATE" != "active" ]; then
    echo "   ⚠ Lambda state='${STATE}' after ${MAX_WAIT}s — proceeding"
fi

# ── 5. Wire S3 → Lambda notification ─────────
echo ""
echo "🔔 [5/5] Setting up S3 → Lambda event notification"

LAMBDA_ARN=$(awslocal lambda get-function \
    --function-name "${FUNC_NAME}" \
    --region "${REGION}" \
    --query 'Configuration.FunctionArn' \
    --output text)

echo "   ↳ ARN: ${LAMBDA_ARN}"

# Clear then set (idempotent)
awslocal s3api put-bucket-notification-configuration \
    --bucket "${BUCKET}" \
    --notification-configuration '{}' \
    --region "${REGION}" 2>/dev/null || true
sleep 1

awslocal s3api put-bucket-notification-configuration \
    --bucket "${BUCKET}" \
    --notification-configuration "{
        \"LambdaFunctionConfigurations\": [{
            \"Id\": \"ocr-upload-trigger\",
            \"LambdaFunctionArn\": \"${LAMBDA_ARN}\",
            \"Events\": [\"s3:ObjectCreated:*\"],
            \"Filter\": {
                \"Key\": {
                    \"FilterRules\": [{
                        \"Name\": \"prefix\",
                        \"Value\": \"uploads/\"
                    }]
                }
            }
        }]
    }" \
    --region "${REGION}"

# Verify
NOTIF=$(awslocal s3api get-bucket-notification-configuration \
    --bucket "${BUCKET}" \
    --region "${REGION}" 2>/dev/null)
NOTIF_COUNT=$(echo "$NOTIF" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(len(d.get('LambdaFunctionConfigurations', [])))
" 2>/dev/null || echo "0")

echo "   ✓ Notification configured (${NOTIF_COUNT} trigger(s))"

# ── Summary ──────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
echo "  ✅ LocalStack Initialization COMPLETE"
echo "════════════════════════════════════════════"
echo "  S3 Bucket  : s3://${BUCKET}"
echo "  Lambda     : ${FUNC_NAME} (${STATE})"
echo "  Trigger    : s3:ObjectCreated:* on uploads/*"
echo "  API Target : ${API_URL}"
echo "  Network    : ocr-net (Lambda containers join this)"
echo "════════════════════════════════════════════"
