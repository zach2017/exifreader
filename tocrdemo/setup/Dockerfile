FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        zip curl jq dos2unix && \
    pip install --no-cache-dir awscli && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /setup

# Generate the provision script entirely inside the container.
# Uses a standard shell heredoc inside RUN — no files copied from
# Windows, no CRLF issues, no BuildKit required.
RUN cat > /setup/provision.sh << 'ENDOFSCRIPT'
#!/bin/bash
set -euo pipefail

EP="${LOCALSTACK_URL:-http://localstack:4566}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="file-uploads"

aws_cmd() {
    aws --endpoint-url="$EP" --region="$REGION" --no-cli-pager "$@"
}

echo ""
echo "============================================"
echo "  PROVISIONING LOCALSTACK RESOURCES"
echo "============================================"
echo "  Endpoint: $EP"
echo "============================================"

echo ""
echo "Checking lambda source files..."
ls -la /lambdas/ 2>/dev/null || { echo "ERROR: /lambdas/ not mounted!"; exit 1; }
test -f /lambdas/file_router.py || { echo "ERROR: file_router.py missing!"; exit 1; }
test -f /lambdas/file_processor.py || { echo "ERROR: file_processor.py missing!"; exit 1; }
echo "  OK: both lambda files found"

echo ""
echo "Waiting for LocalStack..."
for i in $(seq 1 60); do
    if curl -sf "$EP/_localstack/health" > /dev/null 2>&1; then
        echo "  LocalStack ready (attempt $i)"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: LocalStack not ready after 60 attempts"; exit 1
    fi
    echo "  waiting... ($i/60)"
    sleep 2
done
echo "  Stabilizing..."
sleep 5

echo ""
echo "Creating S3 bucket: $BUCKET"
aws_cmd s3 mb "s3://$BUCKET" 2>/dev/null || echo "  bucket already exists"
echo "Setting CORS..."
cat > /tmp/cors.json << 'XEOF'
{"CORSRules":[{"AllowedHeaders":["*"],"AllowedMethods":["GET","PUT","POST","DELETE","HEAD"],"AllowedOrigins":["*"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3600}]}
XEOF
aws_cmd s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration file:///tmp/cors.json
echo "  DONE"

echo ""
echo "Creating IAM role..."
ROLE_ARN="arn:aws:iam::000000000000:role/lambda-exec-role"
cat > /tmp/trust.json << 'XEOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}
XEOF
aws_cmd iam create-role --role-name lambda-exec-role \
    --assume-role-policy-document file:///tmp/trust.json > /dev/null 2>&1 || echo "  role exists"
aws_cmd iam attach-role-policy --role-name lambda-exec-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess 2>/dev/null || true
aws_cmd iam attach-role-policy --role-name lambda-exec-role \
    --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess 2>/dev/null || true
echo "  DONE"

echo ""
echo "Packaging lambdas..."
mkdir -p /tmp/pkg
cp /lambdas/file_router.py /tmp/pkg/
cp /lambdas/file_processor.py /tmp/pkg/
dos2unix /tmp/pkg/*.py 2>/dev/null || true
cd /tmp/pkg
zip -j /tmp/file-router.zip file_router.py
zip -j /tmp/file-processor.zip file_processor.py
echo "  file-router.zip:    $(wc -c < /tmp/file-router.zip) bytes"
echo "  file-processor.zip: $(wc -c < /tmp/file-processor.zip) bytes"

echo ""
echo "Deploying: file-processor"
aws_cmd lambda create-function \
    --function-name file-processor \
    --runtime python3.11 \
    --handler file_processor.handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/file-processor.zip \
    --timeout 60 --memory-size 256 \
    --environment "Variables={LOCALSTACK_ENDPOINT=http://localhost:4566}" \
    > /dev/null 2>&1 && echo "  CREATED" || {
    aws_cmd lambda update-function-code --function-name file-processor \
        --zip-file fileb:///tmp/file-processor.zip > /dev/null 2>&1
    echo "  UPDATED"
}

echo ""
echo "Deploying: file-router"
aws_cmd lambda create-function \
    --function-name file-router \
    --runtime python3.11 \
    --handler file_router.handler \
    --role "$ROLE_ARN" \
    --zip-file fileb:///tmp/file-router.zip \
    --timeout 60 --memory-size 256 \
    --environment "Variables={LOCALSTACK_ENDPOINT=http://localhost:4566}" \
    > /dev/null 2>&1 && echo "  CREATED" || {
    aws_cmd lambda update-function-code --function-name file-router \
        --zip-file fileb:///tmp/file-router.zip > /dev/null 2>&1
    echo "  UPDATED"
}

echo ""
echo "Wiring S3 event notification..."
LAMBDA_ARN=$(aws_cmd lambda get-function --function-name file-router \
    --query 'Configuration.FunctionArn' --output text)
echo "  ARN: $LAMBDA_ARN"
echo "{\"LambdaFunctionConfigurations\":[{\"LambdaFunctionArn\":\"$LAMBDA_ARN\",\"Events\":[\"s3:ObjectCreated:*\"]}]}" > /tmp/notif.json
aws_cmd s3api put-bucket-notification-configuration \
    --bucket "$BUCKET" --notification-configuration file:///tmp/notif.json
echo "  DONE: S3 ObjectCreated -> file-router"

echo ""
echo "Verifying..."
echo "  Buckets:"
aws_cmd s3 ls 2>/dev/null | sed 's/^/    /'
echo "  Lambdas:"
aws_cmd lambda list-functions --query 'Functions[].FunctionName' --output text 2>/dev/null | sed 's/^/    /'

echo ""
echo "============================================"
echo "  ALL RESOURCES PROVISIONED"
echo "============================================"
echo "  S3 Bucket:  s3://$BUCKET"
echo "  Lambda 1:   file-router   (S3 trigger)"
echo "  Lambda 2:   file-processor (invoked by L1)"
echo "  Upload UI:  http://localhost:8080"
echo "  LocalStack: http://localhost:4566"
echo "============================================"
ENDOFSCRIPT

RUN chmod +x /setup/provision.sh

ENTRYPOINT ["/bin/bash", "/setup/provision.sh"]
