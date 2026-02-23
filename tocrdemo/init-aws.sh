#!/bin/bash
# ============================================================
# LocalStack Init Script
# Runs automatically when LocalStack is ready.
# Creates: S3 bucket, 2 Lambda functions, S3 event notification
# ============================================================

set -euo pipefail

REGION="us-east-1"
ENDPOINT="http://localhost:4566"
BUCKET="file-uploads"
AWS="aws --endpoint-url=$ENDPOINT --region=$REGION"

echo "============================================"
echo "  🚀 Initializing LocalStack Resources"
echo "============================================"

# ── 1. Create S3 Bucket ─────────────────────────────────────
echo ""
echo "📦 Creating S3 bucket: $BUCKET"
$AWS s3 mb s3://$BUCKET 2>/dev/null || echo "   Bucket already exists"

# Configure CORS for browser uploads
echo "🌐 Configuring CORS on bucket..."
$AWS s3api put-bucket-cors --bucket $BUCKET --cors-configuration '{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
      "AllowedOrigins": ["*"],
      "ExposeHeaders": ["ETag", "x-amz-request-id"],
      "MaxAgeSeconds": 3600
    }
  ]
}'

# ── 2. Create IAM Role for Lambdas ──────────────────────────
echo ""
echo "🔑 Creating IAM execution role..."
$AWS iam create-role \
    --role-name lambda-exec-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }' 2>/dev/null || echo "   Role already exists"

ROLE_ARN="arn:aws:iam::000000000000:role/lambda-exec-role"

# Attach policies
$AWS iam attach-role-policy \
    --role-name lambda-exec-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess 2>/dev/null || true

$AWS iam attach-role-policy \
    --role-name lambda-exec-role \
    --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess 2>/dev/null || true

# ── 3. Package and Create Lambda Functions ───────────────────
echo ""
echo "📦 Packaging Lambda functions..."

# Package file-router (Lambda 1)
cd /etc/localstack/init/ready.d/ 2>/dev/null || cd /tmp
mkdir -p /tmp/lambda-packages

# If lambdas are mounted, use them. Otherwise create from init script
if [ -f /var/lib/localstack/lambdas/file_router.py ]; then
    LAMBDA_SRC="/var/lib/localstack/lambdas"
else
    LAMBDA_SRC="/tmp/lambda-packages"

    # ── Inline Lambda 1: file-router ──
    cat > /tmp/lambda-packages/file_router.py << 'LAMBDA1EOF'
import json
import os
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
PDF_EXTENSIONS = {'.pdf'}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS

LOCALSTACK_ENDPOINT = os.environ.get('LOCALSTACK_ENDPOINT', 'http://localhost:4566')

def get_lambda_client():
    return boto3.client('lambda', endpoint_url=LOCALSTACK_ENDPOINT, region_name='us-east-1',
                        aws_access_key_id='test', aws_secret_access_key='test')

def get_file_extension(key):
    _, ext = os.path.splitext(key)
    return ext.lower()

def classify_file(extension):
    if extension in IMAGE_EXTENSIONS: return 'image'
    elif extension in PDF_EXTENSIONS: return 'pdf'
    return None

def handler(event, context):
    logger.info(f"File Router triggered: {json.dumps(event)}")
    lambda_client = get_lambda_client()
    results = []
    for record in event.get('Records', []):
        s3_info = record.get('s3', {})
        bucket = s3_info.get('bucket', {}).get('name', '')
        key = s3_info.get('object', {}).get('key', '')
        size = s3_info.get('object', {}).get('size', 0)
        extension = get_file_extension(key)
        file_type = classify_file(extension)
        if file_type is None:
            results.append({'key': key, 'status': 'skipped', 'reason': f'Unsupported: {extension}'})
            continue
        payload = {'bucket': bucket, 'key': key, 'size': size, 'file_type': file_type,
                   'extension': extension, 'source_lambda': 'file-router'}
        logger.info(f"Invoking file-processor with: {json.dumps(payload)}")
        try:
            response = lambda_client.invoke(
                FunctionName='file-processor',
                InvocationType='RequestResponse',
                Payload=json.dumps(payload))
            resp_payload = json.loads(response['Payload'].read().decode('utf-8'))
            results.append({'key': key, 'file_type': file_type, 'status': 'processed',
                           'processor_response': resp_payload})
        except Exception as e:
            logger.error(f"Error invoking file-processor: {e}")
            results.append({'key': key, 'status': 'error', 'error': str(e)})
    return {'statusCode': 200, 'body': json.dumps({'message': 'Routing complete', 'results': results})}
LAMBDA1EOF

    # ── Inline Lambda 2: file-processor ──
    cat > /tmp/lambda-packages/file_processor.py << 'LAMBDA2EOF'
import json
import os
import re
import boto3
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LOCALSTACK_ENDPOINT = os.environ.get('LOCALSTACK_ENDPOINT', 'http://localhost:4566')

def get_s3_client():
    return boto3.client('s3', endpoint_url=LOCALSTACK_ENDPOINT, region_name='us-east-1',
                        aws_access_key_id='test', aws_secret_access_key='test')

def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0: return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

def process_image(file_bytes, extension):
    metadata = {'processor': 'image_processor', 'raw_size_bytes': len(file_bytes),
                'formatted_size': format_size(len(file_bytes))}
    try:
        if extension == '.png' and len(file_bytes) >= 24:
            w = int.from_bytes(file_bytes[16:20], 'big')
            h = int.from_bytes(file_bytes[20:24], 'big')
            metadata.update({'width': w, 'height': h, 'dimensions': f"{w}x{h}"})
        elif extension in ('.jpg', '.jpeg'):
            i = 0
            while i < len(file_bytes) - 9:
                if file_bytes[i] == 0xFF and file_bytes[i+1] in (0xC0, 0xC2):
                    h = int.from_bytes(file_bytes[i+5:i+7], 'big')
                    w = int.from_bytes(file_bytes[i+7:i+9], 'big')
                    metadata.update({'width': w, 'height': h, 'dimensions': f"{w}x{h}"})
                    break
                i += 1
        elif extension == '.gif' and len(file_bytes) >= 10:
            w = int.from_bytes(file_bytes[6:8], 'little')
            h = int.from_bytes(file_bytes[8:10], 'little')
            metadata.update({'width': w, 'height': h, 'dimensions': f"{w}x{h}"})
    except Exception as e:
        metadata['dimensions'] = 'unknown'
    return metadata

def process_pdf(file_bytes):
    metadata = {'processor': 'pdf_processor', 'raw_size_bytes': len(file_bytes),
                'formatted_size': format_size(len(file_bytes))}
    content = file_bytes.decode('latin-1', errors='ignore')
    page_count = content.count('/Type /Page') - content.count('/Type /Pages')
    if page_count <= 0:
        m = re.search(r'/Count\s+(\d+)', content)
        page_count = int(m.group(1)) if m else -1
    metadata['page_count'] = page_count
    if content.startswith('%PDF-'): metadata['pdf_version'] = content[5:8]
    metadata['encrypted'] = '/Encrypt' in content
    return metadata

def handler(event, context):
    logger.info(f"File Processor invoked: {json.dumps(event)}")
    bucket, key = event['bucket'], event['key']
    file_type, extension = event['file_type'], event.get('extension', '')
    s3 = get_s3_client()
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        file_bytes = resp['Body'].read()
        content_type = resp.get('ContentType', 'unknown')
        if file_type == 'image': file_metadata = process_image(file_bytes, extension)
        elif file_type == 'pdf': file_metadata = process_pdf(file_bytes)
        else: file_metadata = {'processor': 'generic', 'raw_size_bytes': len(file_bytes)}
        return {'status': 'success', 'file_info': {'bucket': bucket, 'key': key,
                'file_type': file_type, 'content_type': content_type,
                's3_uri': f"s3://{bucket}/{key}"},
                'processing_result': file_metadata, 'invoked_by': event.get('source_lambda', 'unknown'),
                'processed_at': datetime.utcnow().isoformat() + 'Z'}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {'status': 'error', 'error': str(e), 'bucket': bucket, 'key': key}
LAMBDA2EOF
fi

# ── Create ZIP packages ──
echo "📦 Zipping file-router..."
cd /tmp/lambda-packages
zip -j /tmp/file-router.zip "$LAMBDA_SRC/file_router.py"

echo "📦 Zipping file-processor..."
zip -j /tmp/file-processor.zip "$LAMBDA_SRC/file_processor.py"

# ── Create Lambda 1: file-router ──
echo ""
echo "⚡ Creating Lambda: file-router"
$AWS lambda create-function \
    --function-name file-router \
    --runtime python3.11 \
    --handler file_router.handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/file-router.zip \
    --timeout 60 \
    --memory-size 256 \
    --environment "Variables={LOCALSTACK_ENDPOINT=http://localhost:4566}" \
    2>/dev/null || \
$AWS lambda update-function-code \
    --function-name file-router \
    --zip-file fileb:///tmp/file-router.zip

# ── Create Lambda 2: file-processor ──
echo ""
echo "⚡ Creating Lambda: file-processor"
$AWS lambda create-function \
    --function-name file-processor \
    --runtime python3.11 \
    --handler file_processor.handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/file-processor.zip \
    --timeout 60 \
    --memory-size 256 \
    --environment "Variables={LOCALSTACK_ENDPOINT=http://localhost:4566}" \
    2>/dev/null || \
$AWS lambda update-function-code \
    --function-name file-processor \
    --zip-file fileb:///tmp/file-processor.zip

# ── 4. Configure S3 Event Notification → Lambda 1 ───────────
echo ""
echo "🔔 Setting up S3 event notification → file-router"

LAMBDA_ARN=$($AWS lambda get-function --function-name file-router --query 'Configuration.FunctionArn' --output text)

$AWS s3api put-bucket-notification-configuration \
    --bucket $BUCKET \
    --notification-configuration "{
        \"LambdaFunctionConfigurations\": [{
            \"LambdaFunctionArn\": \"$LAMBDA_ARN\",
            \"Events\": [\"s3:ObjectCreated:*\"]
        }]
    }"

echo ""
echo "============================================"
echo "  ✅ LocalStack Setup Complete!"
echo "============================================"
echo ""
echo "  📦 S3 Bucket:    s3://$BUCKET"
echo "  ⚡ Lambda 1:     file-router (S3 trigger)"
echo "  ⚡ Lambda 2:     file-processor (invoked by L1)"
echo "  🔔 S3 Events:    ObjectCreated → file-router"
echo "  🌐 Endpoint:     http://localhost:4566"
echo "  🖥️  Frontend:     http://localhost:8080"
echo ""
echo "============================================"
