#!/bin/sh
set -e

ENDPOINT="http://localstack:4566"
REGION="us-east-1"

echo "═══════════════════════════════════════════"
echo "  Setting up LocalStack AWS resources"
echo "═══════════════════════════════════════════"

# ── 1. Create S3 Buckets ──
echo "▶ Creating S3 buckets..."
aws --endpoint-url="$ENDPOINT" s3 mb s3://ocr-uploads --region "$REGION" 2>/dev/null || true
aws --endpoint-url="$ENDPOINT" s3 mb s3://ocr-output --region "$REGION" 2>/dev/null || true

# Set CORS on upload bucket for web form
aws --endpoint-url="$ENDPOINT" s3api put-bucket-cors --bucket ocr-uploads --cors-configuration '{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST"],
      "AllowedOrigins": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}' --region "$REGION"

echo "  ✓ S3 buckets created (ocr-uploads, ocr-output)"

# ── 2. Create SQS Queue ──
echo "▶ Creating SQS queue..."
aws --endpoint-url="$ENDPOINT" sqs create-queue \
    --queue-name ocr-results \
    --region "$REGION" 2>/dev/null || true

echo "  ✓ SQS queue created (ocr-results)"

# ── 3. Create Lambda Function ──
echo "▶ Creating Lambda function..."

# Create a dummy zip (LocalStack needs it for create-function even with image)
cd /tmp
echo "placeholder" > dummy.txt
zip -q function.zip dummy.txt

aws --endpoint-url="$ENDPOINT" lambda create-function \
    --function-name ocr-processor \
    --runtime provided.al2023 \
    --handler bootstrap \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --zip-file fileb:///tmp/function.zip \
    --timeout 120 \
    --memory-size 512 \
    --environment "Variables={AWS_ENDPOINT_URL=$ENDPOINT,AWS_DEFAULT_REGION=$REGION,AWS_ACCESS_KEY_ID=test,AWS_SECRET_ACCESS_KEY=test}" \
    --region "$REGION" 2>/dev/null || true

echo "  ✓ Lambda function created (ocr-processor)"

# ── 4. Configure S3 Event Notification → Lambda ──
echo "▶ Configuring S3 → Lambda trigger..."

LAMBDA_ARN="arn:aws:lambda:${REGION}:000000000000:function:ocr-processor"

aws --endpoint-url="$ENDPOINT" s3api put-bucket-notification-configuration \
    --bucket ocr-uploads \
    --notification-configuration "{
        \"LambdaFunctionConfigurations\": [
            {
                \"LambdaFunctionArn\": \"$LAMBDA_ARN\",
                \"Events\": [\"s3:ObjectCreated:*\"],
                \"Filter\": {
                    \"Key\": {
                        \"FilterRules\": [
                            {\"Name\": \"suffix\", \"Value\": \".png\"},
                            {\"Name\": \"suffix\", \"Value\": \".jpg\"},
                            {\"Name\": \"suffix\", \"Value\": \".jpeg\"},
                            {\"Name\": \"suffix\", \"Value\": \".tiff\"},
                            {\"Name\": \"suffix\", \"Value\": \".bmp\"}
                        ]
                    }
                }
            }
        ]
    }" \
    --region "$REGION"

echo "  ✓ S3 event notification configured"

# ── 5. Verify setup ──
echo ""
echo "═══════════════════════════════════════════"
echo "  Verification"
echo "═══════════════════════════════════════════"
echo "▶ S3 Buckets:"
aws --endpoint-url="$ENDPOINT" s3 ls --region "$REGION"
echo "▶ SQS Queues:"
aws --endpoint-url="$ENDPOINT" sqs list-queues --region "$REGION"
echo "▶ Lambda Functions:"
aws --endpoint-url="$ENDPOINT" lambda list-functions --query 'Functions[].FunctionName' --region "$REGION"
echo ""
echo "✅ All resources configured successfully!"
