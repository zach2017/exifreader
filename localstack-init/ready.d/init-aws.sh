#!/bin/bash
# ──────────────────────────────────────────────
# LocalStack bootstrap: S3 bucket + Lambda + S3 event notification
# ──────────────────────────────────────────────
set -e

echo "⏳ Waiting for LocalStack to be ready..."
awslocal s3 ls 2>/dev/null || sleep 5

echo "📦 Creating S3 bucket: ${S3_BUCKET:-ocr-documents}"
awslocal s3 mb "s3://${S3_BUCKET:-ocr-documents}" --region "${AWS_REGION:-us-east-1}" 2>/dev/null || true

echo "📋 Packaging Lambda function..."
cd /etc/localstack/init/ready.d
zip -j /tmp/lambda.zip /opt/lambda/handler.py

echo "🔧 Creating Lambda function: ocr-trigger"
awslocal lambda create-function \
    --function-name ocr-trigger \
    --runtime python3.12 \
    --handler handler.handler \
    --zip-file fileb:///tmp/lambda.zip \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --timeout 300 \
    --memory-size 256 \
    --environment "Variables={API_BASE_URL=${API_BASE_URL:-http://api-server:8000}}" \
    --region "${AWS_REGION:-us-east-1}" \
    2>/dev/null || \
awslocal lambda update-function-code \
    --function-name ocr-trigger \
    --zip-file fileb:///tmp/lambda.zip \
    --region "${AWS_REGION:-us-east-1}"

echo "🔔 Setting up S3 → Lambda event notification..."
LAMBDA_ARN=$(awslocal lambda get-function --function-name ocr-trigger --query 'Configuration.FunctionArn' --output text --region "${AWS_REGION:-us-east-1}")

awslocal s3api put-bucket-notification-configuration \
    --bucket "${S3_BUCKET:-ocr-documents}" \
    --notification-configuration "{
        \"LambdaFunctionConfigurations\": [{
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
    --region "${AWS_REGION:-us-east-1}"

echo "✅ LocalStack initialization complete!"
echo "   Bucket : ${S3_BUCKET:-ocr-documents}"
echo "   Lambda : ocr-trigger"
echo "   Trigger: s3:ObjectCreated:* → uploads/*"
