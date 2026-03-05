#!/bin/bash
set -euo pipefail

echo "============================================"
echo "  Initializing AWS Resources on LocalStack"
echo "============================================"

# ─── Create S3 Bucket ───
echo "[+] Creating S3 bucket: pdf-images"
awslocal s3 mb s3://pdf-images
awslocal s3api put-bucket-cors --bucket pdf-images --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST"],
      "AllowedHeaders": ["*"]
    }
  ]
}'

# ─── Create SQS Queue ───
echo "[+] Creating SQS queue: pdf-processing"
awslocal sqs create-queue --queue-name pdf-processing --attributes '{
  "VisibilityTimeout": "60",
  "MessageRetentionPeriod": "86400"
}'

# ─── Verify ───
echo ""
echo "[✓] S3 Buckets:"
awslocal s3 ls

echo ""
echo "[✓] SQS Queues:"
awslocal sqs list-queues

echo ""
echo "============================================"
echo "  All resources created successfully!"
echo "============================================"
