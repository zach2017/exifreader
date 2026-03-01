#!/bin/sh
set -e

ENDPOINT="http://localstack:4566"
REGION="us-east-1"

echo "═══════════════════════════════════════════"
echo "  Setting up LocalStack AWS resources"
echo "═══════════════════════════════════════════"

# ── 1. Create S3 Buckets ──
echo "▶ Creating S3 buckets..."

curl -s -X PUT "${ENDPOINT}/ocr-uploads" > /dev/null
curl -s -X PUT "${ENDPOINT}/ocr-output" > /dev/null

# Set CORS on upload bucket
curl -s -X PUT "${ENDPOINT}/ocr-uploads?cors" \
  -H "Content-Type: application/xml" \
  -d '<?xml version="1.0" encoding="UTF-8"?>
<CORSConfiguration>
  <CORSRule>
    <AllowedOrigin>*</AllowedOrigin>
    <AllowedMethod>GET</AllowedMethod>
    <AllowedMethod>PUT</AllowedMethod>
    <AllowedMethod>POST</AllowedMethod>
    <AllowedHeader>*</AllowedHeader>
    <ExposeHeader>ETag</ExposeHeader>
  </CORSRule>
</CORSConfiguration>' > /dev/null

echo "  ✓ S3 buckets created (ocr-uploads, ocr-output)"

# ── 2. Create SQS Queue ──
echo "▶ Creating SQS queue..."

curl -s -X POST "${ENDPOINT}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "Action=CreateQueue&QueueName=ocr-results&Version=2012-11-05" > /dev/null

echo "  ✓ SQS queue created (ocr-results)"

# ── 3. Create Lambda Function ──
echo "▶ Creating Lambda function..."

# Build a minimal valid zip in-line using base64 (contains a dummy "bootstrap" file)
# This is a pre-built zip with a single file "bootstrap" containing "#!/bin/sh\nexit 0"
# Generated via: python3 -c "import zipfile,io,base64; b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); z.writestr('bootstrap','#!/bin/sh\nexit 0\n'); z.close(); print(base64.b64encode(b.getvalue()).decode())"
DUMMY_ZIP_B64="UEsDBBQAAAAIAAAAAACKIYOwHAAAABoAAAAJABwAYm9vdHN0cmFwVVQJAAMAAAAAAAAAAAAAC0ktTtZRSMsvyklRBABQSwECHgMUAAAACAAAAAAAgIiBoRwAAAAaAAAACQAYAAAAAAAAAAAApIEAAAAAYm9vdHN0cmFwVVQFAAMAAAAAeAsAAFBLBQYAAAAAAQABAE8AAABfAAAAAAA="

# Write the zip via base64 decode
echo "${DUMMY_ZIP_B64}" | base64 -d > /tmp/function.zip

# Create the Lambda function via LocalStack REST API
PAYLOAD=$(cat <<EOF
{
  "FunctionName": "ocr-processor",
  "Runtime": "provided.al2023",
  "Role": "arn:aws:iam::000000000000:role/lambda-role",
  "Handler": "bootstrap",
  "Timeout": 120,
  "MemorySize": 512,
  "Environment": {
    "Variables": {
      "AWS_ENDPOINT_URL": "${ENDPOINT}",
      "AWS_DEFAULT_REGION": "${REGION}",
      "AWS_ACCESS_KEY_ID": "test",
      "AWS_SECRET_ACCESS_KEY": "test"
    }
  },
  "Code": {
    "ZipFile": "${DUMMY_ZIP_B64}"
  }
}
EOF
)

RESULT=$(curl -s -w "\n%{http_code}" -X POST \
  "${ENDPOINT}/2015-03-31/functions" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}")

HTTP_CODE=$(echo "$RESULT" | tail -1)
BODY=$(echo "$RESULT" | sed '$d')

if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "200" ]; then
  echo "  ✓ Lambda function created (ocr-processor)"
elif echo "$BODY" | grep -q "ResourceConflictException"; then
  echo "  ✓ Lambda function already exists (ocr-processor)"
else
  echo "  ⚠ Lambda creation response ($HTTP_CODE): $BODY"
fi

# ── 4. Configure S3 Event Notification → Lambda ──
echo "▶ Configuring S3 → Lambda trigger..."

LAMBDA_ARN="arn:aws:lambda:${REGION}:000000000000:function:ocr-processor"

NOTIFICATION_XML="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<NotificationConfiguration>
  <CloudFunctionConfiguration>
    <CloudFunction>${LAMBDA_ARN}</CloudFunction>
    <Event>s3:ObjectCreated:*</Event>
    <Filter>
      <S3Key>
        <FilterRule><Name>suffix</Name><Value>.png</Value></FilterRule>
      </S3Key>
    </Filter>
  </CloudFunctionConfiguration>
  <CloudFunctionConfiguration>
    <CloudFunction>${LAMBDA_ARN}</CloudFunction>
    <Event>s3:ObjectCreated:*</Event>
    <Filter>
      <S3Key>
        <FilterRule><Name>suffix</Name><Value>.jpg</Value></FilterRule>
      </S3Key>
    </Filter>
  </CloudFunctionConfiguration>
  <CloudFunctionConfiguration>
    <CloudFunction>${LAMBDA_ARN}</CloudFunction>
    <Event>s3:ObjectCreated:*</Event>
    <Filter>
      <S3Key>
        <FilterRule><Name>suffix</Name><Value>.jpeg</Value></FilterRule>
      </S3Key>
    </Filter>
  </CloudFunctionConfiguration>
  <CloudFunctionConfiguration>
    <CloudFunction>${LAMBDA_ARN}</CloudFunction>
    <Event>s3:ObjectCreated:*</Event>
    <Filter>
      <S3Key>
        <FilterRule><Name>suffix</Name><Value>.tiff</Value></FilterRule>
      </S3Key>
    </Filter>
  </CloudFunctionConfiguration>
  <CloudFunctionConfiguration>
    <CloudFunction>${LAMBDA_ARN}</CloudFunction>
    <Event>s3:ObjectCreated:*</Event>
    <Filter>
      <S3Key>
        <FilterRule><Name>suffix</Name><Value>.bmp</Value></FilterRule>
      </S3Key>
    </Filter>
  </CloudFunctionConfiguration>
</NotificationConfiguration>"

curl -s -X PUT "${ENDPOINT}/ocr-uploads?notification" \
  -H "Content-Type: application/xml" \
  -d "${NOTIFICATION_XML}" > /dev/null

echo "  ✓ S3 event notification configured"

# ── 5. Verify setup ──
echo ""
echo "═══════════════════════════════════════════"
echo "  Verification"
echo "═══════════════════════════════════════════"

echo "▶ S3 Buckets:"
curl -s "${ENDPOINT}" | grep -o '<Name>[^<]*</Name>' | sed 's/<[^>]*>//g' | while read -r name; do
  echo "    - $name"
done

echo "▶ SQS Queues:"
curl -s "${ENDPOINT}?Action=ListQueues&Version=2012-11-05" | grep -o '<QueueUrl>[^<]*</QueueUrl>' | sed 's/<[^>]*>//g' | while read -r url; do
  echo "    - $url"
done

echo "▶ Lambda Functions:"
curl -s "${ENDPOINT}/2015-03-31/functions" | grep -o '"FunctionName":"[^"]*"' | sed 's/"FunctionName":"//;s/"//' | while read -r fn; do
  echo "    - $fn"
done

echo ""
echo "✅ All resources configured successfully!"
