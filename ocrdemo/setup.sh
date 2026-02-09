#!/bin/bash
set -e

echo "================================================"
echo "  Setting up OCR Lambda Function"
echo "================================================"

# Package the Lambda
echo "Packaging Lambda function..."
cd /etc/localstack/init/ready.d/lambda-code
zip -r /tmp/ocr-lambda.zip handler.py

# Create the Lambda function
echo "Creating Lambda function..."
awslocal lambda create-function \
    --function-name ocr-service \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --zip-file fileb:///tmp/ocr-lambda.zip \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --timeout 60 \
    --memory-size 512

echo ""
echo "================================================"
echo "  OCR Lambda deployed successfully!"
echo "  Invoke via: POST http://localhost:4566/2015-03-31/functions/ocr-service/invocations"
echo "================================================"
