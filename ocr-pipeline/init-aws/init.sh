#!/bin/bash
set -euo pipefail

echo "============================================="
echo "  Initializing LocalStack resources..."
echo "============================================="

ENDPOINT="http://localhost:4566"
REGION="us-east-1"
BUCKET="ocr-uploads"
QUEUE="ocr-jobs"

# ── Create S3 bucket ──
echo "[1/3] Creating S3 bucket: $BUCKET"
awslocal s3 mb "s3://$BUCKET" --region "$REGION" 2>/dev/null || echo "  Bucket already exists."

# Set CORS so the browser can talk to S3 directly if needed
awslocal s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET","PUT","POST","DELETE","HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}'
echo "  ✔ Bucket created with CORS."

# ── Create SQS queue ──
echo "[2/3] Creating SQS queue: $QUEUE"
awslocal sqs create-queue --queue-name "$QUEUE" --region "$REGION" 2>/dev/null || echo "  Queue already exists."
QUEUE_URL=$(awslocal sqs get-queue-url --queue-name "$QUEUE" --region "$REGION" --query 'QueueUrl' --output text)
QUEUE_ARN=$(awslocal sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
echo "  ✔ Queue URL:  $QUEUE_URL"
echo "  ✔ Queue ARN:  $QUEUE_ARN"

# ── Wire S3 event → SQS notification ──
echo "[3/3] Configuring S3 → SQS event notification"
awslocal s3api put-bucket-notification-configuration --bucket "$BUCKET" --notification-configuration "{
  \"QueueConfigurations\": [
    {
      \"QueueArn\": \"$QUEUE_ARN\",
      \"Events\": [\"s3:ObjectCreated:*\"]
    }
  ]
}"
echo "  ✔ S3 notifications wired to SQS."

echo ""
echo "============================================="
echo "  LocalStack ready!"
echo "  Bucket: s3://$BUCKET"
echo "  Queue:  $QUEUE_URL"
echo "============================================="
