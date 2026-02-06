#!/bin/bash
# Deploy the OCR Lambda function to LocalStack

set -e

echo "=== Deploying OCR Lambda ==="

# Create the zip from the handler
cd /etc/localstack/init/ready.d/lambda_src
zip -j /tmp/ocr_lambda.zip handler.py

# Create the Lambda function
awslocal lambda create-function \
    --function-name ocr-extract-text \
    --runtime python3.12 \
    --handler handler.handler \
    --zip-file fileb:///tmp/ocr_lambda.zip \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --timeout 60 \
    --memory-size 512

echo "=== Lambda deployed successfully ==="

# Quick smoke test
echo "=== Smoke test ==="
awslocal lambda invoke \
    --function-name ocr-extract-text \
    --payload '{"image_b64":"","image_ext":"png","image_name":"test"}' \
    /tmp/lambda_test_out.json || true

cat /tmp/lambda_test_out.json
echo ""
echo "=== Init complete ==="
