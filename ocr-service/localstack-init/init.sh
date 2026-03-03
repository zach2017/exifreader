#!/bin/bash
set -x

ENDPOINT="http://localhost:4566"
REGION="us-east-1"

echo "============================================"
echo "  Initializing LocalStack Resources"
echo "============================================"

# Wait for LocalStack to be fully ready
echo ""
echo "--- Waiting for LocalStack services ---"
for i in $(seq 1 30); do
    HEALTH=$(curl -sf "$ENDPOINT/_localstack/health" 2>/dev/null)
    if echo "$HEALTH" | grep -q '"sqs": "running"' && echo "$HEALTH" | grep -q '"s3": "running"'; then
        echo "LocalStack S3 and SQS are running."
        break
    fi
    echo "  Attempt $i/30 - waiting for S3 + SQS..."
    sleep 2
done

echo ""
echo "--- Creating S3 Buckets ---"
for BUCKET in uploads extracted-text tmp-files tmp-extracted-text; do
    echo "Creating bucket: $BUCKET"
    awslocal s3 mb "s3://$BUCKET" --region "$REGION" 2>&1 || true
done

echo ""
echo "--- Verifying S3 Buckets ---"
awslocal s3 ls --region "$REGION"

echo ""
echo "--- Creating SQS Queues ---"
for QUEUE in file-processing ocr-processing ocr-complete; do
    echo "Creating queue: $QUEUE"
    awslocal sqs create-queue \
        --queue-name "$QUEUE" \
        --region "$REGION" \
        --attributes '{"VisibilityTimeout":"300","MessageRetentionPeriod":"86400"}' \
        2>&1 || true
done

echo ""
echo "--- Verifying SQS Queues ---"
awslocal sqs list-queues --region "$REGION"

echo ""
echo "--- Queue URLs ---"
for QUEUE in file-processing ocr-processing ocr-complete; do
    URL=$(awslocal sqs get-queue-url --queue-name "$QUEUE" --region "$REGION" --output text 2>/dev/null)
    echo "  $QUEUE -> $URL"
done

echo ""
echo "============================================"
echo "  LocalStack initialization complete!"
echo "  S3 Buckets: uploads, extracted-text,"
echo "              tmp-files, tmp-extracted-text"
echo "  SQS Queues: file-processing,"
echo "              ocr-processing, ocr-complete"
echo "============================================"
