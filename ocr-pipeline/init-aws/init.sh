#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────
# Init script — runs once at startup with AWS CLI v2
# Creates: S3 buckets, SQS queue, Lambda function, event wiring
# ─────────────────────────────────────────────────────────────────

ENDPOINT="${LOCALSTACK_URL:-http://localstack:4566}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
UPLOAD_BUCKET="ocr-uploads"
RESULT_BUCKET="ocr-results"
QUEUE="ocr-jobs"
LAMBDA_NAME="ocr-processor"
LAMBDA_IMAGE="ocr-lambda:latest"
ACCOUNT_ID="000000000000"

# ── AWS CLI v2 wrapper pointing at LocalStack ──
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

# ── [0/6] Wait for LocalStack readiness ──
echo "[0/6] Waiting for LocalStack at $ENDPOINT ..."
RETRIES=0
MAX_RETRIES=40
until curl -sf "${ENDPOINT}/_localstack/health" | jq -e '.services.s3 == "running" or .services.s3 == "available"' > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        echo "  ✘ LocalStack did not become ready in time."
        exit 1
    fi
    echo "  waiting… ($RETRIES/$MAX_RETRIES)"
    sleep 3
done

# Also wait for Lambda service
until curl -sf "${ENDPOINT}/_localstack/health" | jq -e '.services.lambda == "running" or .services.lambda == "available"' > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        echo "  ✘ Lambda service did not become ready."
        exit 1
    fi
    echo "  waiting for lambda service… ($RETRIES/$MAX_RETRIES)"
    sleep 2
done

echo "  ✔ LocalStack is ready."
echo ""

# ── [1/6] Create upload bucket ──
echo "[1/6] Creating S3 upload bucket: $UPLOAD_BUCKET"
awsv2 s3api create-bucket --bucket "$UPLOAD_BUCKET" 2>/dev/null || echo "  (already exists)"

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

# ── [2/6] Create results bucket ──
echo "[2/6] Creating S3 results bucket: $RESULT_BUCKET"
awsv2 s3api create-bucket --bucket "$RESULT_BUCKET" 2>/dev/null || echo "  (already exists)"
echo "  ✔ Results bucket ready."
echo ""

# ── [3/6] Create SQS queue ──
echo "[3/6] Creating SQS queue: $QUEUE"
awsv2 sqs create-queue \
    --queue-name "$QUEUE" \
    --attributes '{"VisibilityTimeout":"120","MessageRetentionPeriod":"3600"}' \
    > /dev/null 2>/dev/null || echo "  (already exists)"

QUEUE_URL=$(awsv2 sqs get-queue-url --queue-name "$QUEUE" | jq -r '.QueueUrl')
QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT_ID}:${QUEUE}"

echo "  ✔ Queue URL: $QUEUE_URL"
echo "  ✔ Queue ARN: $QUEUE_ARN"
echo ""

# ── [4/6] Deploy Lambda function from Docker image ──
echo "[4/6] Creating Lambda function: $LAMBDA_NAME"
echo "      Image: $LAMBDA_IMAGE"

# Clean up any existing function
awsv2 lambda delete-function --function-name "$LAMBDA_NAME" > /dev/null 2>/dev/null || true
sleep 2

awsv2 lambda create-function \
    --function-name "$LAMBDA_NAME" \
    --package-type Image \
    --code "ImageUri=$LAMBDA_IMAGE" \
    --role "arn:aws:iam::${ACCOUNT_ID}:role/lambda-role" \
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

# ── [5/6] Wire S3 → SQS event notification ──
echo "[5/6] Configuring S3 → SQS event notification"

# Using heredoc to avoid shell escaping issues with CLI v2
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

# ── [6/6] Wire SQS → Lambda event source mapping ──
echo "[6/6] Creating SQS → Lambda event source mapping"

# Delete any existing mappings
EXISTING_UUIDS=$(awsv2 lambda list-event-source-mappings \
    --function-name "$LAMBDA_NAME" \
    | jq -r '.EventSourceMappings[].UUID // empty' 2>/dev/null || true)

for uuid in $EXISTING_UUIDS; do
    echo "  Deleting old mapping: $uuid"
    awsv2 lambda delete-event-source-mapping --uuid "$uuid" > /dev/null 2>/dev/null || true
done

awsv2 lambda create-event-source-mapping \
    --function-name "$LAMBDA_NAME" \
    --event-source-arn "$QUEUE_ARN" \
    --batch-size 1 \
    --enabled \
    > /dev/null

echo "  ✔ SQS → Lambda event source mapping created."

# ── Verify everything ──
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
echo "$LAMBDA_STATE"

echo -n "  Event source map:  "
ESM_COUNT=$(awsv2 lambda list-event-source-mappings --function-name "$LAMBDA_NAME" \
    | jq '.EventSourceMappings | length' 2>/dev/null || echo "0")
echo "${ESM_COUNT} mapping(s)"

echo ""
echo "============================================="
echo "  ✔ All resources initialized!"
echo ""
echo "  Pipeline:  S3 upload"
echo "           → SQS event notification"
echo "           → Lambda cold start (on-demand)"
echo "           → Tesseract OCR"
echo "           → Result to S3"
echo "============================================="
