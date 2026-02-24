#!/bin/bash
###############################################################################
# LocalStack Initialization Script
# Runs automatically when LocalStack container starts (mounted to init/ready.d)
# Creates all AWS resources: S3, SQS, DynamoDB, Lambda, Step Functions, API GW
###############################################################################

set -euo pipefail

REGION="us-east-1"
ACCOUNT_ID="000000000000"
ENDPOINT="http://localhost:4566"
LAMBDA_DIR="/opt/lambdas"

echo "=============================================="
echo "  Initializing AWS Resources on LocalStack"
echo "=============================================="

# ─── Helper ─────────────────────────────────────────────
awslocal() {
    aws --endpoint-url=$ENDPOINT --region=$REGION "$@"
}

# ─── 1. S3 Bucket ──────────────────────────────────────
echo ""
echo "▸ Creating S3 bucket..."
awslocal s3 mb s3://docproc-bucket 2>/dev/null || true
awslocal s3api put-bucket-cors --bucket docproc-bucket --cors-configuration '{
  "CORSRules": [{
    "AllowedOrigins": ["*"],
    "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }]
}'
echo "  ✓ S3 bucket 'docproc-bucket' created with CORS"

# ─── 2. SQS Queues ─────────────────────────────────────
echo ""
echo "▸ Creating SQS queues..."

# Dead Letter Queues first
for DLQ in file-router-dlq text-extract-dlq ocr-dlq; do
    awslocal sqs create-queue --queue-name $DLQ --attributes '{
        "MessageRetentionPeriod": "1209600"
    }' 2>/dev/null || true
    echo "  ✓ DLQ '$DLQ' created"
done

# Main queues with DLQ redrive policy
awslocal sqs create-queue --queue-name file-router-queue --attributes '{
    "VisibilityTimeout": "120",
    "MessageRetentionPeriod": "86400",
    "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:file-router-dlq\",\"maxReceiveCount\":\"3\"}"
}' 2>/dev/null || true
echo "  ✓ Queue 'file-router-queue' created (timeout: 120s, DLQ after 3 retries)"

awslocal sqs create-queue --queue-name text-extract-queue --attributes '{
    "VisibilityTimeout": "360",
    "MessageRetentionPeriod": "86400",
    "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:text-extract-dlq\",\"maxReceiveCount\":\"3\"}"
}' 2>/dev/null || true
echo "  ✓ Queue 'text-extract-queue' created (timeout: 360s, DLQ after 3 retries)"

awslocal sqs create-queue --queue-name ocr-queue --attributes '{
    "VisibilityTimeout": "600",
    "MessageRetentionPeriod": "86400",
    "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:ocr-dlq\",\"maxReceiveCount\":\"3\"}"
}' 2>/dev/null || true
echo "  ✓ Queue 'ocr-queue' created (timeout: 600s, DLQ after 3 retries)"

# ─── 3. DynamoDB Table ─────────────────────────────────
echo ""
echo "▸ Creating DynamoDB table..."
awslocal dynamodb create-table \
    --table-name document-metadata \
    --attribute-definitions \
        AttributeName=file_id,AttributeType=S \
    --key-schema \
        AttributeName=file_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || true
echo "  ✓ DynamoDB table 'document-metadata' created (on-demand capacity)"

# ─── 4. IAM Role for Lambda ────────────────────────────
echo ""
echo "▸ Creating IAM role for Lambda..."
awslocal iam create-role \
    --role-name lambda-exec-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }' 2>/dev/null || true
echo "  ✓ IAM role 'lambda-exec-role' created"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/lambda-exec-role"

# ─── 5. Lambda Functions ───────────────────────────────
echo ""
echo "▸ Packaging and creating Lambda functions..."

# Package each Lambda
for FUNC_DIR in file-router text-extractor ocr-extractor; do
    cd ${LAMBDA_DIR}/${FUNC_DIR}
    
    # Install dependencies if requirements.txt exists
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt -t ./package/ --quiet 2>/dev/null || true
        cd package && zip -r9 /tmp/${FUNC_DIR}.zip . --quiet 2>/dev/null && cd ..
        zip -g /tmp/${FUNC_DIR}.zip handler.py --quiet 2>/dev/null
    else
        zip -j /tmp/${FUNC_DIR}.zip handler.py --quiet 2>/dev/null
    fi
    
    echo "  ✓ Packaged '${FUNC_DIR}'"
done

# Create File Router Lambda
awslocal lambda create-function \
    --function-name file-router \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --role $ROLE_ARN \
    --zip-file fileb:///tmp/file-router.zip \
    --timeout 30 \
    --memory-size 256 \
    --environment "Variables={
        S3_BUCKET=docproc-bucket,
        TEXT_EXTRACT_QUEUE_URL=http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/text-extract-queue,
        OCR_QUEUE_URL=http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ocr-queue,
        DYNAMODB_TABLE=document-metadata,
        STEP_FUNCTION_ARN=arn:aws:states:us-east-1:000000000000:stateMachine:pdf-processing-pipeline,
        ELASTICSEARCH_URL=http://docproc-elasticsearch:9200,
        AWS_ENDPOINT_URL=http://localhost:4566
    }" 2>/dev/null || true
echo "  ✓ Lambda 'file-router' created"

# Create Text Extractor Lambda
awslocal lambda create-function \
    --function-name text-extractor \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --role $ROLE_ARN \
    --zip-file fileb:///tmp/text-extractor.zip \
    --timeout 120 \
    --memory-size 1024 \
    --environment "Variables={
        S3_BUCKET=docproc-bucket,
        DYNAMODB_TABLE=document-metadata,
        ELASTICSEARCH_URL=http://docproc-elasticsearch:9200,
        AWS_ENDPOINT_URL=http://localhost:4566
    }" 2>/dev/null || true
echo "  ✓ Lambda 'text-extractor' created (1024MB, 120s timeout)"

# Create OCR Extractor Lambda
awslocal lambda create-function \
    --function-name ocr-extractor \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --role $ROLE_ARN \
    --zip-file fileb:///tmp/ocr-extractor.zip \
    --timeout 300 \
    --memory-size 2048 \
    --environment "Variables={
        S3_BUCKET=docproc-bucket,
        DYNAMODB_TABLE=document-metadata,
        ELASTICSEARCH_URL=http://docproc-elasticsearch:9200,
        AWS_ENDPOINT_URL=http://localhost:4566
    }" 2>/dev/null || true
echo "  ✓ Lambda 'ocr-extractor' created (2048MB, 300s timeout)"

# ─── 6. SQS → Lambda Event Source Mappings ─────────────
echo ""
echo "▸ Creating SQS → Lambda event source mappings..."

awslocal lambda create-event-source-mapping \
    --function-name file-router \
    --event-source-arn arn:aws:sqs:${REGION}:${ACCOUNT_ID}:file-router-queue \
    --batch-size 1 \
    --enabled 2>/dev/null || true
echo "  ✓ file-router-queue → file-router Lambda"

awslocal lambda create-event-source-mapping \
    --function-name text-extractor \
    --event-source-arn arn:aws:sqs:${REGION}:${ACCOUNT_ID}:text-extract-queue \
    --batch-size 1 \
    --enabled 2>/dev/null || true
echo "  ✓ text-extract-queue → text-extractor Lambda"

awslocal lambda create-event-source-mapping \
    --function-name ocr-extractor \
    --event-source-arn arn:aws:sqs:${REGION}:${ACCOUNT_ID}:ocr-queue \
    --batch-size 1 \
    --enabled 2>/dev/null || true
echo "  ✓ ocr-queue → ocr-extractor Lambda"

# ─── 7. Step Function ──────────────────────────────────
echo ""
echo "▸ Creating Step Function state machine..."

STEP_FUNCTION_DEF='{
  "Comment": "PDF Processing Pipeline — Extract images, route to OCR and text extraction",
  "StartAt": "ExtractImagesFromPDF",
  "States": {
    "ExtractImagesFromPDF": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:000000000000:function:text-extractor",
      "Parameters": {
        "action": "extract_images",
        "file_id.$": "$.file_id",
        "s3_key.$": "$.s3_key"
      },
      "ResultPath": "$.extraction_result",
      "Next": "ParallelProcessing",
      "Retry": [{ "ErrorEquals": ["States.ALL"], "MaxAttempts": 2, "BackoffRate": 2 }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "ProcessingFailed" }]
    },
    "ParallelProcessing": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "SendOCRMessages",
          "States": {
            "SendOCRMessages": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:us-east-1:000000000000:function:file-router",
              "Parameters": {
                "action": "send_ocr_batch",
                "file_id.$": "$.file_id",
                "image_keys.$": "$.extraction_result.image_keys"
              },
              "End": true,
              "Retry": [{ "ErrorEquals": ["States.ALL"], "MaxAttempts": 2 }]
            }
          }
        },
        {
          "StartAt": "SendTextExtractMessage",
          "States": {
            "SendTextExtractMessage": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:us-east-1:000000000000:function:file-router",
              "Parameters": {
                "action": "send_text_extract",
                "file_id.$": "$.file_id",
                "s3_key.$": "$.s3_key"
              },
              "End": true,
              "Retry": [{ "ErrorEquals": ["States.ALL"], "MaxAttempts": 2 }]
            }
          }
        }
      ],
      "ResultPath": "$.parallel_result",
      "Next": "UpdateMetadata",
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "ProcessingFailed" }]
    },
    "UpdateMetadata": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:000000000000:function:file-router",
      "Parameters": {
        "action": "update_metadata",
        "file_id.$": "$.file_id",
        "status": "PROCESSING"
      },
      "End": true
    },
    "ProcessingFailed": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:000000000000:function:file-router",
      "Parameters": {
        "action": "update_metadata",
        "file_id.$": "$.file_id",
        "status": "ERROR"
      },
      "End": true
    }
  }
}'

awslocal stepfunctions create-state-machine \
    --name pdf-processing-pipeline \
    --definition "$STEP_FUNCTION_DEF" \
    --role-arn $ROLE_ARN \
    2>/dev/null || true
echo "  ✓ Step Function 'pdf-processing-pipeline' created"

# ─── 8. S3 Event Notification ──────────────────────────
echo ""
echo "▸ Configuring S3 event notification..."
awslocal s3api put-bucket-notification-configuration \
    --bucket docproc-bucket \
    --notification-configuration '{
        "QueueConfigurations": [{
            "QueueArn": "arn:aws:sqs:us-east-1:000000000000:file-router-queue",
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {
                "Key": {
                    "FilterRules": [{
                        "Name": "prefix",
                        "Value": "uploads/"
                    }]
                }
            }
        }]
    }' 2>/dev/null || true
echo "  ✓ S3 event → file-router-queue on uploads/"

# ─── 9. API Gateway ────────────────────────────────────
echo ""
echo "▸ Creating API Gateway..."

REST_API_ID=$(awslocal apigateway create-rest-api \
    --name 'DocProc API' \
    --description 'Document Processing API' \
    --query 'id' --output text 2>/dev/null)

ROOT_ID=$(awslocal apigateway get-resources \
    --rest-api-id $REST_API_ID \
    --query 'items[0].id' --output text 2>/dev/null)

# /upload resource
UPLOAD_ID=$(awslocal apigateway create-resource \
    --rest-api-id $REST_API_ID \
    --parent-id $ROOT_ID \
    --path-part upload \
    --query 'id' --output text 2>/dev/null)

awslocal apigateway put-method \
    --rest-api-id $REST_API_ID \
    --resource-id $UPLOAD_ID \
    --http-method POST \
    --authorization-type NONE 2>/dev/null || true

# /files resource
FILES_ID=$(awslocal apigateway create-resource \
    --rest-api-id $REST_API_ID \
    --parent-id $ROOT_ID \
    --path-part files \
    --query 'id' --output text 2>/dev/null)

awslocal apigateway put-method \
    --rest-api-id $REST_API_ID \
    --resource-id $FILES_ID \
    --http-method GET \
    --authorization-type NONE 2>/dev/null || true

# /search resource
SEARCH_ID=$(awslocal apigateway create-resource \
    --rest-api-id $REST_API_ID \
    --parent-id $ROOT_ID \
    --path-part search \
    --query 'id' --output text 2>/dev/null)

awslocal apigateway put-method \
    --rest-api-id $REST_API_ID \
    --resource-id $SEARCH_ID \
    --http-method GET \
    --authorization-type NONE 2>/dev/null || true

echo "  ✓ API Gateway created with /upload, /files, /search endpoints"
echo "  API URL: http://localhost:4566/restapis/${REST_API_ID}/local/_user_request_/"

# Save API ID for frontend
echo "${REST_API_ID}" > /tmp/api-gateway-id.txt

echo ""
echo "=============================================="
echo "  ✅ All AWS Resources Initialized!"
echo "=============================================="
echo ""
echo "  S3:              s3://docproc-bucket"
echo "  SQS Queues:      file-router-queue, text-extract-queue, ocr-queue"
echo "  DynamoDB:        document-metadata"
echo "  Lambdas:         file-router, text-extractor, ocr-extractor"
echo "  Step Function:   pdf-processing-pipeline"
echo "  API Gateway:     ${REST_API_ID}"
echo ""
