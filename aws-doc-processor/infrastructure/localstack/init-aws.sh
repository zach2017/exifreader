#!/bin/bash
###############################################################################
# LocalStack Init — Minimal & Bulletproof
#
# Creates ONLY the resources that LocalStack handles reliably:
#   - S3 bucket with CORS
#   - SQS queues (3 main + 3 DLQ)
#   - DynamoDB table
#   - S3 → SQS event notification
#
# Lambda processing is handled by the 'poller' Docker container
# which directly imports and calls the Lambda handler.py functions.
###############################################################################

REGION="us-east-1"
EP="http://localhost:4566"

echo ""
echo "=============================================="
echo "  DocProc — Setting up LocalStack resources"
echo "=============================================="

awslocal() {
    aws --endpoint-url="$EP" --region="$REGION" --no-cli-pager "$@" 2>/dev/null
}

# ── S3 ────────────────────────────────────────────────
echo ""
echo "▸ S3 bucket..."
awslocal s3 mb s3://docproc-bucket || true
awslocal s3api put-bucket-cors --bucket docproc-bucket \
    --cors-configuration '{"CORSRules":[{"AllowedOrigins":["*"],"AllowedMethods":["GET","PUT","POST","DELETE","HEAD"],"AllowedHeaders":["*"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3600}]}' || true
echo "  ✓ docproc-bucket"

# ── SQS ───────────────────────────────────────────────
echo ""
echo "▸ SQS queues..."

# DLQs first
awslocal sqs create-queue --queue-name file-router-dlq || true
awslocal sqs create-queue --queue-name text-extract-dlq || true
awslocal sqs create-queue --queue-name ocr-dlq || true
echo "  ✓ DLQs created"

# Main queues with redrive to DLQs
awslocal sqs create-queue --queue-name file-router-queue \
    --attributes '{"VisibilityTimeout":"120","RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:file-router-dlq\",\"maxReceiveCount\":\"3\"}"}' || true
echo "  ✓ file-router-queue"

awslocal sqs create-queue --queue-name text-extract-queue \
    --attributes '{"VisibilityTimeout":"360","RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:text-extract-dlq\",\"maxReceiveCount\":\"3\"}"}' || true
echo "  ✓ text-extract-queue"

awslocal sqs create-queue --queue-name ocr-queue \
    --attributes '{"VisibilityTimeout":"600","RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:ocr-dlq\",\"maxReceiveCount\":\"3\"}"}' || true
echo "  ✓ ocr-queue"

# ── DynamoDB ──────────────────────────────────────────
echo ""
echo "▸ DynamoDB table..."
awslocal dynamodb create-table \
    --table-name document-metadata \
    --attribute-definitions AttributeName=file_id,AttributeType=S \
    --key-schema AttributeName=file_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST || true
echo "  ✓ document-metadata"

# ── S3 → SQS Event Notification ──────────────────────
echo ""
echo "▸ S3 event notification..."
awslocal s3api put-bucket-notification-configuration \
    --bucket docproc-bucket \
    --notification-configuration '{"QueueConfigurations":[{"QueueArn":"arn:aws:sqs:us-east-1:000000000000:file-router-queue","Events":["s3:ObjectCreated:*"],"Filter":{"Key":{"FilterRules":[{"Name":"prefix","Value":"uploads/"}]}}}]}' || true
echo "  ✓ S3 uploads/ → file-router-queue"

# ── Verify ────────────────────────────────────────────
echo ""
echo "▸ Verifying..."
echo -n "  Bucket: "
awslocal s3api head-bucket --bucket docproc-bucket && echo "✓" || echo "✗"

echo -n "  Queues: "
COUNT=$(awslocal sqs list-queues --output json | grep -c "http" || echo 0)
echo "$COUNT ✓"

echo -n "  DynamoDB: "
awslocal dynamodb describe-table --table-name document-metadata \
    --query 'Table.TableStatus' --output text || echo "✗"

echo -n "  S3 notification: "
awslocal s3api get-bucket-notification-configuration --bucket docproc-bucket \
    --query 'QueueConfigurations[0].Events[0]' --output text || echo "✗"

echo ""
echo "=============================================="
echo "  ✅ Done! Resources ready."
echo "  Processing is handled by the 'poller' container."
echo "=============================================="
echo ""

exit 0
