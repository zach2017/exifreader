#!/bin/bash
# ============================================================
# Test Script — Verify S3 → Lambda → Lambda pipeline
# Run after: docker compose up -d (wait for setup to finish)
# ============================================================

set -euo pipefail

EP="http://localhost:4566"
BUCKET="file-uploads"
A="aws --endpoint-url=$EP --region=us-east-1"

G='\033[0;32m' Y='\033[1;33m' C='\033[0;36m' R='\033[0;31m' N='\033[0m'

echo -e "${C}══════════════════════════════════════${N}"
echo -e "${C}  🧪 S3 → Lambda Pipeline Test${N}"
echo -e "${C}══════════════════════════════════════${N}"

# 1. Health
echo -e "\n${Y}1. LocalStack health${N}"
curl -sf "$EP/_localstack/health" | python3 -m json.tool 2>/dev/null || echo "⚠️  Not ready"

# 2. Verify resources
echo -e "\n${Y}2. Resources${N}"
echo "   Buckets:"; $A s3 ls 2>/dev/null | sed 's/^/   /'
echo "   Lambdas:"; $A lambda list-functions --query 'Functions[].FunctionName' --output text 2>/dev/null | sed 's/^/   /'
echo "   S3 Notifications:"
$A s3api get-bucket-notification-configuration --bucket $BUCKET 2>/dev/null | python3 -m json.tool | sed 's/^/   /'

# 3. Create test files
echo -e "\n${Y}3. Creating test files${N}"

cat > /tmp/test.pdf << 'EOF'
%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
trailer<</Size 4/Root 1 0 R>>
startxref
0
%%EOF
EOF
echo "   ✅ test.pdf"

printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x02\x00\x00\x00\x90\x91h6\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB\x60\x82' > /tmp/test.png
echo "   ✅ test.png (16x16)"

echo "hello" > /tmp/test.txt
echo "   ✅ test.txt (unsupported)"

# 4. Upload
echo -e "\n${Y}4. Uploading to S3${N}"
$A s3 cp /tmp/test.pdf s3://$BUCKET/uploads/test.pdf --quiet && echo -e "   ${G}✅ PDF uploaded${N}"
$A s3 cp /tmp/test.png s3://$BUCKET/uploads/test.png --quiet && echo -e "   ${G}✅ PNG uploaded${N}"
$A s3 cp /tmp/test.txt s3://$BUCKET/uploads/test.txt --quiet && echo -e "   ${G}✅ TXT uploaded${N}"

# 5. Wait for S3 event → Lambda chain
echo -e "\n${Y}5. Waiting 3s for Lambda chain...${N}"
sleep 3

# 6. Invoke file-processor directly to verify
echo -e "\n${Y}6. Direct Lambda invocations${N}"

echo -e "   ${C}── PDF ──${N}"
$A lambda invoke --function-name file-processor \
    --payload '{"bucket":"file-uploads","key":"uploads/test.pdf","size":200,"file_type":"pdf","extension":".pdf","source_lambda":"test-script"}' \
    /tmp/r1.json > /dev/null 2>&1
python3 -m json.tool /tmp/r1.json 2>/dev/null | sed 's/^/   /'

echo -e "\n   ${C}── PNG ──${N}"
$A lambda invoke --function-name file-processor \
    --payload '{"bucket":"file-uploads","key":"uploads/test.png","size":68,"file_type":"image","extension":".png","source_lambda":"test-script"}' \
    /tmp/r2.json > /dev/null 2>&1
python3 -m json.tool /tmp/r2.json 2>/dev/null | sed 's/^/   /'

echo -e "\n   ${C}── file-router (full chain) ──${N}"
$A lambda invoke --function-name file-router \
    --payload '{"Records":[{"s3":{"bucket":{"name":"file-uploads"},"object":{"key":"uploads/test.pdf","size":200}}}]}' \
    /tmp/r3.json > /dev/null 2>&1
python3 -m json.tool /tmp/r3.json 2>/dev/null | sed 's/^/   /'

# 7. List files
echo -e "\n${Y}7. Files in S3${N}"
$A s3 ls s3://$BUCKET/uploads/ | sed 's/^/   /'

echo -e "\n${G}══════════════════════════════════════${N}"
echo -e "${G}  ✅ All tests complete!${N}"
echo -e "${G}══════════════════════════════════════${N}"
echo -e "  🖥️  UI:        http://localhost:8080"
echo -e "  📡 LocalStack: http://localhost:4566"
