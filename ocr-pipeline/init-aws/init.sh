#!/bin/bash
set -euo pipefail

ENDPOINT="http://localstack:4566"
REGION="us-east-1"
UPLOAD_BUCKET="ocr-uploads"
RESULT_BUCKET="ocr-results"
QUEUE="ocr-jobs"
LAMBDA_NAME="ocr-processor"
LAMBDA_IMAGE="ocr-lambda:latest"
ACCOUNT_ID="000000000000"

# Helper: run AWS CLI against LocalStack
aws_local() {
    aws --endpoint-url="$ENDPOINT" --region "$REGION" \
        --no-cli-pager "$@"
}

echo "============================================="
echo "  Initializing AWS resources in LocalStack"
echo "============================================="

# ── Wait for LocalStack to be fully ready ──
echo ""
echo "[0/6] Waiting for LocalStack services..."
for i in $(seq 1 30); do
    if aws_local s3 ls >/dev/null 2>&1; then
        echo "  ✔ LocalStack is ready."
        break
    fi
    echo "  Waiting... ($i)"
    sleep 2
done

# ── 1. Create upload bucket ──
echo ""
echo "[1/6] Creating S3 upload bucket: $UPLOAD_BUCKET"
aws_local s3 mb "s3://$UPLOAD_BUCKET" 2>/dev/null || echo "  (already exists)"

aws_local s3api put-bucket-cors --bucket "$UPLOAD_BUCKET" --cors-configuration '{
  "CORSRules": [{
    "AllowedOrigins": ["*"],
    "AllowedMethods": ["GET","PUT","POST","DELETE","HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"]
  }]
}'
echo "  ✔ Upload bucket ready."

# ── 2. Create results bucket ──
echo ""
echo "[2/6] Creating S3 results bucket: $RESULT_BUCKET"
aws_local s3 mb "s3://$RESULT_BUCKET" 2>/dev/null || echo "  (already exists)"
echo "  ✔ Results bucket ready."

# ── 3. Create SQS queue ──
echo ""
echo "[3/6] Creating SQS queue: $QUEUE"
aws_local sqs create-queue \
    --queue-name "$QUEUE" \
    --attributes '{
        "VisibilityTimeout": "120",
        "MessageRetentionPeriod": "3600"
    }' 2>/dev/null || echo "  (already exists)"

QUEUE_URL=$(aws_local sqs get-queue-url --queue-name "$QUEUE" --query 'QueueUrl' --output text)
QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT_ID}:${QUEUE}"
echo "  ✔ Queue URL: $QUEUE_URL"
echo "  ✔ Queue ARN: $QUEUE_ARN"

# ── 4. Deploy Lambda function from Docker image ──
echo ""
echo "[4/6] Creating Lambda function: $LAMBDA_NAME (image: $LAMBDA_IMAGE)"

# Delete if exists (for re-runs)
aws_local lambda delete-function --function-name "$LAMBDA_NAME" 2>/dev/null || true
sleep 1

aws_local lambda create-function \
    --function-name "$LAMBDA_NAME" \
    --package-type Image \
    --code ImageUri="$LAMBDA_IMAGE" \
    --role "arn:aws:iam::${ACCOUNT_ID}:role/lambda-role" \
    --timeout 120 \
    --memory-size 1024 \
    --environment "Variables={S3_ENDPOINT=http://localstack:4566,RESULT_BUCKET=${RESULT_BUCKET},AWS_ACCESS_KEY_ID=test,AWS_SECRET_ACCESS_KEY=test,AWS_DEFAULT_REGION=${REGION}}"

echo "  ✔ Lambda function created."

# Wait for the function to become Active
echo "  Waiting for Lambda to become Active..."
for i in $(seq 1 20); do
    STATE=$(aws_local lambda get-function --function-name "$LAMBDA_NAME" \
        --query 'Configuration.State' --output text 2>/dev/null || echo "Pending")
    if [ "$STATE" = "Active" ]; then
        echo "  ✔ Lambda is Active."
        break
    fi
    echo "  State: $STATE ($i)"
    sleep 2
done

# ── 5. Wire S3 → SQS notification ──
echo ""
echo "[5/6] Configuring S3 → SQS event notification"
aws_local s3api put-bucket-notification-configuration \
    --bucket "$UPLOAD_BUCKET" \
    --notification-configuration "{
        \"QueueConfigurations\": [{
            \"QueueArn\": \"${QUEUE_ARN}\",
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
    }"
echo "  ✔ S3 → SQS notification configured."

# ── 6. Wire SQS → Lambda event source mapping ──
echo ""
echo "[6/6] Creating SQS → Lambda event source mapping"

# Delete existing mappings for this function
EXISTING=$(aws_local lambda list-event-source-mappings \
    --function-name "$LAMBDA_NAME" \
    --query 'EventSourceMappings[].UUID' --output text 2>/dev/null || true)

for uuid in $EXISTING; do
    aws_local lambda delete-event-source-mapping --uuid "$uuid" 2>/dev/null || true
done

aws_local lambda create-event-source-mapping \
    --function-name "$LAMBDA_NAME" \
    --event-source-arn "$QUEUE_ARN" \
    --batch-size 1 \
    --enabled

echo "  ✔ SQS → Lambda event source mapping created."

# ── Summary ──
echo ""
echo "============================================="
echo "  ✔ All resources created!"
echo ""
echo "  Upload bucket:  s3://$UPLOAD_BUCKET"
echo "  Results bucket: s3://$RESULT_BUCKET"
echo "  SQS Queue:      $QUEUE_URL"
echo "  Lambda:         $LAMBDA_NAME ($LAMBDA_IMAGE)"
echo ""
echo "  Pipeline: S3 upload → SQS → Lambda → S3 result"
echo "============================================="
