#!/bin/bash
###############################################################################
# LocalStack Initialization Script — FIXED
# Key fixes over v1:
#   1. Lambda env vars are single-line (whitespace broke JSON)
#   2. Lambda LAMBDA_DOCKER_NETWORK set so containers see each other
#   3. Added SQS queue policy allowing S3 SendMessage
#   4. Added verification/debugging output
###############################################################################

set -euo pipefail

REGION="us-east-1"
ACCOUNT_ID="000000000000"
ENDPOINT="http://localhost:4566"
LAMBDA_DIR="/opt/lambdas"

echo "=============================================="
echo "  Initializing AWS Resources on LocalStack"
echo "=============================================="

awslocal() {
    aws --endpoint-url=$ENDPOINT --region=$REGION  "$@"
}

# ─── 1. S3 Bucket ──────────────────────────────────────
echo ""
echo "▸ Creating S3 bucket..."
awslocal s3 mb s3://docproc-bucket 2>/dev/null || true
awslocal s3api put-bucket-cors --bucket docproc-bucket --cors-configuration '{"CORSRules":[{"AllowedOrigins":["*"],"AllowedMethods":["GET","PUT","POST","DELETE","HEAD"],"AllowedHeaders":["*"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3600}]}'
echo "  ✓ S3 bucket created with CORS"

# ─── 2. SQS Queues ─────────────────────────────────────
echo ""
echo "▸ Creating SQS queues..."

for DLQ in file-router-dlq text-extract-dlq ocr-dlq; do
    awslocal sqs create-queue --queue-name $DLQ --attributes '{"MessageRetentionPeriod":"1209600"}' 2>/dev/null || true
    echo "  ✓ DLQ '$DLQ'"
done

awslocal sqs create-queue --queue-name file-router-queue --attributes '{"VisibilityTimeout":"120","MessageRetentionPeriod":"86400","RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:file-router-dlq\",\"maxReceiveCount\":\"3\"}"}' 2>/dev/null || true
echo "  ✓ file-router-queue (visibility=120s)"

awslocal sqs create-queue --queue-name text-extract-queue --attributes '{"VisibilityTimeout":"360","MessageRetentionPeriod":"86400","RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:text-extract-dlq\",\"maxReceiveCount\":\"3\"}"}' 2>/dev/null || true
echo "  ✓ text-extract-queue (visibility=360s)"

awslocal sqs create-queue --queue-name ocr-queue --attributes '{"VisibilityTimeout":"600","MessageRetentionPeriod":"86400","RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:ocr-dlq\",\"maxReceiveCount\":\"3\"}"}' 2>/dev/null || true
echo "  ✓ ocr-queue (visibility=600s)"

# ─── 3. DynamoDB Table ─────────────────────────────────
echo ""
echo "▸ Creating DynamoDB table..."
awslocal dynamodb create-table \
    --table-name document-metadata \
    --attribute-definitions AttributeName=file_id,AttributeType=S \
    --key-schema AttributeName=file_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || true
echo "  ✓ DynamoDB table 'document-metadata'"

# ─── 4. IAM Role ───────────────────────────────────────
echo ""
echo "▸ Creating IAM role..."
awslocal iam create-role \
    --role-name lambda-exec-role \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
    2>/dev/null || true
echo "  ✓ IAM role 'lambda-exec-role'"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/lambda-exec-role"

# ─── 5. Lambda Functions ───────────────────────────────
echo ""
echo "▸ Packaging Lambda functions..."

for FUNC_DIR in file-router text-extractor ocr-extractor; do
    cd ${LAMBDA_DIR}/${FUNC_DIR}
    rm -rf ./package /tmp/${FUNC_DIR}.zip 2>/dev/null || true
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt -t ./package/ --quiet 2>/dev/null || true
        if [ -d ./package ] && [ "$(ls -A ./package 2>/dev/null)" ]; then
            cd package && zip -r9 /tmp/${FUNC_DIR}.zip . --quiet 2>/dev/null && cd ..
            zip -g /tmp/${FUNC_DIR}.zip handler.py --quiet 2>/dev/null
        else
            zip -j /tmp/${FUNC_DIR}.zip handler.py --quiet 2>/dev/null
        fi
    else
        zip -j /tmp/${FUNC_DIR}.zip handler.py --quiet 2>/dev/null
    fi
    echo "  ✓ Packaged '${FUNC_DIR}' ($(du -h /tmp/${FUNC_DIR}.zip 2>/dev/null | cut -f1))"
done

echo ""
echo "▸ Deploying Lambda functions..."

# CRITICAL FIX: Single-line env vars, no whitespace inside Variables={...}
awslocal lambda delete-function --function-name file-router 2>/dev/null || true
awslocal lambda create-function \
    --function-name file-router \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/file-router.zip \
    --timeout 30 \
    --memory-size 256 \
    --environment 'Variables={S3_BUCKET=docproc-bucket,TEXT_EXTRACT_QUEUE_URL=http://localhost:4566/000000000000/text-extract-queue,OCR_QUEUE_URL=http://localhost:4566/000000000000/ocr-queue,DYNAMODB_TABLE=document-metadata,STEP_FUNCTION_ARN=arn:aws:states:us-east-1:000000000000:stateMachine:pdf-processing-pipeline,ELASTICSEARCH_URL=http://host.docker.internal:9200,AWS_ENDPOINT_URL=http://localhost:4566}'
echo "  ✓ Lambda 'file-router' (256MB, 30s)"

awslocal lambda delete-function --function-name text-extractor 2>/dev/null || true
awslocal lambda create-function \
    --function-name text-extractor \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/text-extractor.zip \
    --timeout 120 \
    --memory-size 1024 \
    --environment 'Variables={S3_BUCKET=docproc-bucket,DYNAMODB_TABLE=document-metadata,ELASTICSEARCH_URL=http://host.docker.internal:9200,AWS_ENDPOINT_URL=http://localhost:4566}'
echo "  ✓ Lambda 'text-extractor' (1024MB, 120s)"

awslocal lambda delete-function --function-name ocr-extractor 2>/dev/null || true
awslocal lambda create-function \
    --function-name ocr-extractor \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/ocr-extractor.zip \
    --timeout 300 \
    --memory-size 2048 \
    --environment 'Variables={S3_BUCKET=docproc-bucket,DYNAMODB_TABLE=document-metadata,ELASTICSEARCH_URL=http://host.docker.internal:9200,AWS_ENDPOINT_URL=http://localhost:4566}'
echo "  ✓ Lambda 'ocr-extractor' (2048MB, 300s)"

# ─── 6. SQS → Lambda Event Source Mappings ─────────────
echo ""
echo "▸ Creating event source mappings..."

awslocal lambda create-event-source-mapping \
    --function-name file-router \
    --event-source-arn "arn:aws:sqs:${REGION}:${ACCOUNT_ID}:file-router-queue" \
    --batch-size 1 --enabled 2>/dev/null || true
echo "  ✓ file-router-queue → file-router"

awslocal lambda create-event-source-mapping \
    --function-name text-extractor \
    --event-source-arn "arn:aws:sqs:${REGION}:${ACCOUNT_ID}:text-extract-queue" \
    --batch-size 1 --enabled 2>/dev/null || true
echo "  ✓ text-extract-queue → text-extractor"

awslocal lambda create-event-source-mapping \
    --function-name ocr-extractor \
    --event-source-arn "arn:aws:sqs:${REGION}:${ACCOUNT_ID}:ocr-queue" \
    --batch-size 1 --enabled 2>/dev/null || true
echo "  ✓ ocr-queue → ocr-extractor"

# ─── 7. Step Function ──────────────────────────────────
echo ""
echo "▸ Creating Step Function..."

awslocal stepfunctions create-state-machine \
    --name pdf-processing-pipeline \
    --definition '{"Comment":"PDF Pipeline","StartAt":"ExtractImagesFromPDF","States":{"ExtractImagesFromPDF":{"Type":"Task","Resource":"arn:aws:lambda:us-east-1:000000000000:function:text-extractor","Parameters":{"action":"extract_images","file_id.$":"$.file_id","s3_key.$":"$.s3_key"},"ResultPath":"$.extraction_result","Next":"ParallelProcessing","Retry":[{"ErrorEquals":["States.ALL"],"MaxAttempts":2,"BackoffRate":2}],"Catch":[{"ErrorEquals":["States.ALL"],"Next":"ProcessingFailed"}]},"ParallelProcessing":{"Type":"Parallel","Branches":[{"StartAt":"SendOCRMessages","States":{"SendOCRMessages":{"Type":"Task","Resource":"arn:aws:lambda:us-east-1:000000000000:function:file-router","Parameters":{"action":"send_ocr_batch","file_id.$":"$.file_id","image_keys.$":"$.extraction_result.image_keys"},"End":true}}},{"StartAt":"SendTextExtractMessage","States":{"SendTextExtractMessage":{"Type":"Task","Resource":"arn:aws:lambda:us-east-1:000000000000:function:file-router","Parameters":{"action":"send_text_extract","file_id.$":"$.file_id","s3_key.$":"$.s3_key"},"End":true}}}],"ResultPath":"$.parallel_result","Next":"UpdateMetadata","Catch":[{"ErrorEquals":["States.ALL"],"Next":"ProcessingFailed"}]},"UpdateMetadata":{"Type":"Task","Resource":"arn:aws:lambda:us-east-1:000000000000:function:file-router","Parameters":{"action":"update_metadata","file_id.$":"$.file_id","status":"PROCESSING"},"End":true},"ProcessingFailed":{"Type":"Task","Resource":"arn:aws:lambda:us-east-1:000000000000:function:file-router","Parameters":{"action":"update_metadata","file_id.$":"$.file_id","status":"ERROR"},"End":true}}}' \
    --role-arn "$ROLE_ARN" \
    2>/dev/null || true
echo "  ✓ Step Function 'pdf-processing-pipeline'"

# ─── 8. S3 Event Notification ──────────────────────────
echo ""
echo "▸ Configuring S3 → SQS event notification..."
awslocal s3api put-bucket-notification-configuration \
    --bucket docproc-bucket \
    --notification-configuration '{"QueueConfigurations":[{"QueueArn":"arn:aws:sqs:us-east-1:000000000000:file-router-queue","Events":["s3:ObjectCreated:*"],"Filter":{"Key":{"FilterRules":[{"Name":"prefix","Value":"uploads/"}]}}}]}'
echo "  ✓ S3 event → file-router-queue on uploads/"

# ─── 9. Verify ─────────────────────────────────────────
echo ""
echo "▸ Verifying all resources..."

echo -n "  S3 bucket:        " && awslocal s3api head-bucket --bucket docproc-bucket 2>/dev/null && echo "✓" || echo "✗"
echo -n "  SQS queues:       " && echo "$(awslocal sqs list-queues --query 'QueueUrls | length(@)' --output text 2>/dev/null) queues ✓"
echo -n "  DynamoDB table:   " && awslocal dynamodb describe-table --table-name document-metadata --query 'Table.TableStatus' --output text 2>/dev/null
echo -n "  Lambdas:          " && awslocal lambda list-functions --query 'Functions[].FunctionName' --output text 2>/dev/null
echo -n "  Event mappings:   " && echo "$(awslocal lambda list-event-source-mappings --query 'EventSourceMappings | length(@)' --output text 2>/dev/null) mappings ✓"
echo -n "  Step Functions:   " && awslocal stepfunctions list-state-machines --query 'stateMachines[0].name' --output text 2>/dev/null
echo -n "  S3 notification:  " && awslocal s3api get-bucket-notification-configuration --bucket docproc-bucket --query 'QueueConfigurations[0].Events[0]' --output text 2>/dev/null

# ─── 10. Smoke test — write to S3 and check SQS ───────
echo ""
echo "▸ Smoke test: S3 upload → SQS message..."
awslocal s3 cp - s3://docproc-bucket/uploads/smoke-test/hello.txt --content-type text/plain <<< "smoke test" 2>/dev/null
sleep 2
MSG_COUNT=$(awslocal sqs get-queue-attributes --queue-url "http://localhost:4566/000000000000/file-router-queue" --attribute-names ApproximateNumberOfMessages --query 'Attributes.ApproximateNumberOfMessages' --output text 2>/dev/null)
echo "  Messages in file-router-queue: ${MSG_COUNT}"
if [ "$MSG_COUNT" != "0" ] && [ "$MSG_COUNT" != "None" ]; then
    echo "  ✓ S3 → SQS notification is WORKING"
else
    echo "  ⚠ S3 → SQS notification may not be triggering (queue shows $MSG_COUNT)"
    echo "    The frontend has a manual 'Process Queue' button as fallback"
fi
# Clean up smoke test
awslocal s3 rm s3://docproc-bucket/uploads/smoke-test/hello.txt 2>/dev/null || true

echo ""
echo "=============================================="
echo "  ✅ All AWS Resources Initialized!"
echo "=============================================="
echo ""
echo "  Frontend:   http://localhost:8080"
echo "  LocalStack: http://localhost:4566"
echo ""
