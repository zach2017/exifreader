#!/bin/bash
set -e

echo "═══════════════════════════════════════════"
echo "  Setting up LocalStack AWS resources"
echo "═══════════════════════════════════════════"

# Wait for the lambda zip to be available (built by lambda-builder)
echo "▶ Waiting for Lambda deployment zip..."
RETRIES=0
while [ ! -f /opt/lambda-dist/function.zip ] && [ $RETRIES -lt 60 ]; do
    sleep 2
    RETRIES=$((RETRIES + 1))
done

if [ ! -f /opt/lambda-dist/function.zip ]; then
    echo "  ✗ ERROR: /opt/lambda-dist/function.zip not found after 120s"
    exit 1
fi
echo "  ✓ Lambda zip found"

# ── 1. S3 Buckets ──
echo "▶ Creating S3 buckets..."

awslocal s3 mb s3://ocr-uploads 2>/dev/null || true
awslocal s3 mb s3://ocr-output 2>/dev/null || true

awslocal s3api put-bucket-cors --bucket ocr-uploads --cors-configuration '{
  "CORSRules": [{
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders": ["ETag"]
  }]
}'

awslocal s3api put-bucket-cors --bucket ocr-output --cors-configuration '{
  "CORSRules": [{
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders": ["ETag", "Content-Length", "Content-Type"]
  }]
}'

echo "  ✓ S3 buckets created (ocr-uploads, ocr-output)"

# ── 2. SQS Queue ──
echo "▶ Creating SQS queue..."
awslocal sqs create-queue --queue-name ocr-results 2>/dev/null || true
echo "  ✓ SQS queue created (ocr-results)"

# ── 3. Lambda Function ──
echo "▶ Creating Lambda function with real Go binary..."

awslocal lambda create-function \
    --function-name ocr-processor \
    --runtime provided.al2023 \
    --handler bootstrap \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --zip-file fileb:///opt/lambda-dist/function.zip \
    --timeout 120 \
    --memory-size 1024 \
    --environment "Variables={AWS_ENDPOINT_URL=http://host.docker.internal:4566,AWS_DEFAULT_REGION=us-east-1,AWS_ACCESS_KEY_ID=test,AWS_SECRET_ACCESS_KEY=test}" \
    2>/dev/null || {
    echo "  Updating existing function..."
    awslocal lambda update-function-code \
        --function-name ocr-processor \
        --zip-file fileb:///opt/lambda-dist/function.zip
    awslocal lambda update-function-configuration \
        --function-name ocr-processor \
        --timeout 120 \
        --memory-size 1024 \
        --environment "Variables={AWS_ENDPOINT_URL=http://host.docker.internal:4566,AWS_DEFAULT_REGION=us-east-1,AWS_ACCESS_KEY_ID=test,AWS_SECRET_ACCESS_KEY=test}"
}

# Wait for function to be Active
echo "  Waiting for function to become Active..."
for i in $(seq 1 30); do
    STATE=$(awslocal lambda get-function --function-name ocr-processor --query 'Configuration.State' --output text 2>/dev/null || echo "Pending")
    if [ "$STATE" = "Active" ]; then
        break
    fi
    sleep 2
done

echo "  ✓ Lambda function ready (ocr-processor)"

# ── 4. S3 → Lambda Trigger ──
echo "▶ Configuring S3 → Lambda trigger..."

awslocal s3api put-bucket-notification-configuration \
    --bucket ocr-uploads \
    --notification-configuration '{
        "LambdaFunctionConfigurations": [
            {
                "Id": "ocr-png",
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ocr-processor",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {"Key": {"FilterRules": [{"Name": "suffix", "Value": ".png"}]}}
            },
            {
                "Id": "ocr-jpg",
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ocr-processor",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {"Key": {"FilterRules": [{"Name": "suffix", "Value": ".jpg"}]}}
            },
            {
                "Id": "ocr-jpeg",
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ocr-processor",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {"Key": {"FilterRules": [{"Name": "suffix", "Value": ".jpeg"}]}}
            },
            {
                "Id": "ocr-tiff",
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ocr-processor",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {"Key": {"FilterRules": [{"Name": "suffix", "Value": ".tiff"}]}}
            },
            {
                "Id": "ocr-bmp",
                "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:ocr-processor",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {"Key": {"FilterRules": [{"Name": "suffix", "Value": ".bmp"}]}}
            }
        ]
    }'

echo "  ✓ S3 notification configured"

# ── 5. Verify ──
echo ""
echo "═══════════════════════════════════════════"
echo "  Verification"
echo "═══════════════════════════════════════════"
awslocal s3 ls
awslocal sqs list-queues --output table
awslocal lambda list-functions --query 'Functions[].{Name:FunctionName,Runtime:Runtime,State:State}' --output table
awslocal s3api get-bucket-notification-configuration --bucket ocr-uploads
echo ""
echo "✅ Setup complete!"
