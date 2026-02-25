#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────
# Init script — AWS CLI v2
#
# Deploys Lambda as a ZIP package (LocalStack Community Edition).
# Container images (--package-type Image) require Pro.
#
# The custom runtime image (ocr-lambda-runtime:latest) with
# Tesseract is used via LAMBDA_RUNTIME_IMAGE_MAPPING set in
# docker-compose.yml — this is a free feature.
# ─────────────────────────────────────────────────────────────────

ENDPOINT="${LOCALSTACK_URL:-http://localstack:4566}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
UPLOAD_BUCKET="ocr-uploads"
RESULT_BUCKET="ocr-results"
QUEUE="ocr-jobs"
LAMBDA_NAME="ocr-processor"
ACCOUNT_ID="000000000000"

# Lambda code is mounted from docker-compose volume
LAMBDA_CODE_DIR="/opt/lambda-code"

# ── AWS CLI v2 wrapper ──
awsv2() {
    aws --endpoint-url="$ENDPOINT" \
        --region "$REGION" \
        --no-cli-pager \
        --output json \
        "$@"
}

echo ""
echo "============================================="
echo "  AWS CLI Version:"
aws --version
echo "============================================="
echo ""

# ── [0/7] Wait for LocalStack ──
echo "[0/7] Waiting for LocalStack at $ENDPOINT ..."
RETRIES=0
MAX_RETRIES=40
until curl -sf "${ENDPOINT}/_localstack/health" | jq -e '
    (.services.s3 == "running" or .services.s3 == "available") and
    (.services.sqs == "running" or .services.sqs == "available") and
    (.services.lambda == "running" or .services.lambda == "available")
' > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        echo "  ✘ LocalStack did not become ready."
        curl -sf "${ENDPOINT}/_localstack/health" | jq . || true
        exit 1
    fi
    echo "  waiting… ($RETRIES/$MAX_RETRIES)"
    sleep 3
done
echo "  ✔ LocalStack is ready (s3, sqs, lambda all running)."
echo ""

# ── [1/7] Create upload bucket ──
echo "[1/7] Creating S3 upload bucket: $UPLOAD_BUCKET"
awsv2 s3api create-bucket --bucket "$UPLOAD_BUCKET" > /dev/null 2>&1 || echo "  (already exists)"

awsv2 s3api put-bucket-cors --bucket "$UPLOAD_BUCKET" --cors-configuration '{
  "CORSRules": [{
    "AllowedOrigins": ["*"],
    "AllowedMethods": ["GET","PUT","POST","DELETE","HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"]
  }]
}'
echo "  ✔ Upload bucket ready."
echo ""

# ── [2/7] Create results bucket ──
echo "[2/7] Creating S3 results bucket: $RESULT_BUCKET"
awsv2 s3api create-bucket --bucket "$RESULT_BUCKET" > /dev/null 2>&1 || echo "  (already exists)"
echo "  ✔ Results bucket ready."
echo ""

# ── [3/7] Create SQS queue ──
echo "[3/7] Creating SQS queue: $QUEUE"
awsv2 sqs create-queue \
    --queue-name "$QUEUE" \
    --attributes '{"VisibilityTimeout":"120","MessageRetentionPeriod":"3600"}' \
    > /dev/null 2>&1 || echo "  (already exists)"

QUEUE_URL=$(awsv2 sqs get-queue-url --queue-name "$QUEUE" | jq -r '.QueueUrl')
QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT_ID}:${QUEUE}"

echo "  ✔ Queue URL: $QUEUE_URL"
echo "  ✔ Queue ARN: $QUEUE_ARN"
echo ""

# ── [4/7] Package Lambda handler as zip ──
echo "[4/7] Packaging Lambda handler as zip"

if [ ! -f "${LAMBDA_CODE_DIR}/lambda_handler.py" ]; then
    echo "  ✘ ERROR: ${LAMBDA_CODE_DIR}/lambda_handler.py not found!"
    echo "  Make sure ./lambda is mounted at /opt/lambda-code in docker-compose."
    exit 1
fi

LAMBDA_ZIP="/tmp/lambda-handler.zip"
rm -f "$LAMBDA_ZIP"

# Create zip from the handler file (use -j to strip directory path)
cd "$LAMBDA_CODE_DIR"
zip -j "$LAMBDA_ZIP" lambda_handler.py
cd /

ZIP_SIZE=$(stat -c%s "$LAMBDA_ZIP" 2>/dev/null || stat -f%z "$LAMBDA_ZIP" 2>/dev/null || echo "?")
echo "  ✔ Zip created: $LAMBDA_ZIP ($ZIP_SIZE bytes)"
echo ""

# ── [5/7] Deploy Lambda function (zip package, NOT container image) ──
echo "[5/7] Creating Lambda function: $LAMBDA_NAME"
echo "      Runtime: python3.11 (mapped to ocr-lambda-runtime:latest)"
echo "      Handler: lambda_handler.handler"
echo "      Package: zip (Community Edition compatible)"

# Clean up any existing function
awsv2 lambda delete-function --function-name "$LAMBDA_NAME" > /dev/null 2>&1 || true
sleep 2

# Deploy as zip package with python3.11 runtime
# LocalStack will use ocr-lambda-runtime:latest for this runtime
# (set via LAMBDA_RUNTIME_IMAGE_MAPPING in docker-compose)
awsv2 lambda create-function \
    --function-name "$LAMBDA_NAME" \
    --runtime "python3.11" \
    --handler "lambda_handler.handler" \
    --role "arn:aws:iam::${ACCOUNT_ID}:role/lambda-role" \
    --zip-file "fileb://${LAMBDA_ZIP}" \
    --timeout 120 \
    --memory-size 1024 \
    --environment "Variables={S3_ENDPOINT=${ENDPOINT},RESULT_BUCKET=${RESULT_BUCKET},AWS_ACCESS_KEY_ID=test,AWS_SECRET_ACCESS_KEY=test,AWS_DEFAULT_REGION=${REGION}}" \
    > /dev/null

echo "  ✔ Lambda function created."

# Wait for Active state
echo "  Waiting for Lambda to become Active…"
for i in $(seq 1 30); do
    STATE=$(awsv2 lambda get-function --function-name "$LAMBDA_NAME" \
        | jq -r '.Configuration.State // "Pending"' 2>/dev/null || echo "Pending")
    if [ "$STATE" = "Active" ]; then
        echo "  ✔ Lambda is Active."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ⚠ Lambda state: $STATE (proceeding anyway)"
    else
        echo "  State: $STATE ($i/30)"
        sleep 2
    fi
done
echo ""

# ── [6/7] Wire S3 → SQS event notification ──
echo "[6/7] Configuring S3 → SQS event notification"

NOTIFICATION_CONFIG=$(cat <<EOF
{
  "QueueConfigurations": [{
    "QueueArn": "${QUEUE_ARN}",
    "Events": ["s3:ObjectCreated:*"],
    "Filter": {
      "Key": {
        "FilterRules": [{
          "Name": "prefix",
          "Value": "uploads/"
        }]
      }
    }
  }]
}
EOF
)

awsv2 s3api put-bucket-notification-configuration \
    --bucket "$UPLOAD_BUCKET" \
    --notification-configuration "$NOTIFICATION_CONFIG"
echo "  ✔ S3 → SQS notification configured."
echo ""

# ── [7/7] Wire SQS → Lambda event source mapping ──
echo "[7/7] Creating SQS → Lambda event source mapping"

# Delete any existing mappings
EXISTING_UUIDS=$(awsv2 lambda list-event-source-mappings \
    --function-name "$LAMBDA_NAME" \
    | jq -r '.EventSourceMappings[].UUID // empty' 2>/dev/null || true)

for uuid in $EXISTING_UUIDS; do
    echo "  Removing old mapping: $uuid"
    awsv2 lambda delete-event-source-mapping --uuid "$uuid" > /dev/null 2>&1 || true
done

awsv2 lambda create-event-source-mapping \
    --function-name "$LAMBDA_NAME" \
    --event-source-arn "$QUEUE_ARN" \
    --batch-size 1 \
    --enabled \
    > /dev/null

echo "  ✔ SQS → Lambda event source mapping created."

# ── Verify ──
echo ""
echo "============================================="
echo "  Verification"
echo "============================================="

echo -n "  S3 upload bucket:  "
awsv2 s3api head-bucket --bucket "$UPLOAD_BUCKET" > /dev/null 2>&1 && echo "✔" || echo "✘"

echo -n "  S3 results bucket: "
awsv2 s3api head-bucket --bucket "$RESULT_BUCKET" > /dev/null 2>&1 && echo "✔" || echo "✘"

echo -n "  SQS queue:         "
awsv2 sqs get-queue-url --queue-name "$QUEUE" > /dev/null 2>&1 && echo "✔" || echo "✘"

echo -n "  Lambda function:   "
LAMBDA_STATE=$(awsv2 lambda get-function --function-name "$LAMBDA_NAME" \
    | jq -r '.Configuration.State' 2>/dev/null || echo "NOT FOUND")
LAMBDA_RUNTIME=$(awsv2 lambda get-function --function-name "$LAMBDA_NAME" \
    | jq -r '.Configuration.Runtime' 2>/dev/null || echo "?")
echo "$LAMBDA_STATE (runtime: $LAMBDA_RUNTIME)"

echo -n "  Event source map:  "
ESM_COUNT=$(awsv2 lambda list-event-source-mappings --function-name "$LAMBDA_NAME" \
    | jq '.EventSourceMappings | length' 2>/dev/null || echo "0")
echo "${ESM_COUNT} mapping(s)"

echo ""
echo "============================================="
echo "  ✔ All resources initialized!"
echo ""
echo "  Lambda is deployed as a zip package."
echo "  Runtime image: ocr-lambda-runtime:latest"
echo "  (via LAMBDA_RUNTIME_IMAGE_MAPPING — free)"
echo ""
echo "  Pipeline:  S3 upload"
echo "           → SQS event notification"
echo "           → Lambda cold start (on-demand)"
echo "           → Tesseract OCR"
echo "           → Result to S3"
echo "============================================="
