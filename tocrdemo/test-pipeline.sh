#!/bin/bash
# ============================================================
# Test Script — Verify the full S3 → Lambda → Lambda pipeline
# Run after: docker compose up -d
# ============================================================

set -euo pipefail

ENDPOINT="http://localhost:4566"
BUCKET="file-uploads"
AWS="aws --endpoint-url=$ENDPOINT --region=us-east-1"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  🧪 Testing S3 → Lambda Pipeline${NC}"
echo -e "${CYAN}============================================${NC}"

# ── 1. Check LocalStack health ────────────────────────────────
echo ""
echo -e "${YELLOW}1. Checking LocalStack health...${NC}"
curl -s "$ENDPOINT/_localstack/health" | python3 -m json.tool 2>/dev/null || echo "  ⚠️  LocalStack not ready"

# ── 2. Verify resources exist ─────────────────────────────────
echo ""
echo -e "${YELLOW}2. Verifying resources...${NC}"
echo "   📦 S3 Buckets:"
$AWS s3 ls 2>/dev/null || echo "   No buckets found"

echo "   ⚡ Lambda Functions:"
$AWS lambda list-functions --query 'Functions[].FunctionName' --output text 2>/dev/null || echo "   No functions found"

echo "   🔔 S3 Notifications:"
$AWS s3api get-bucket-notification-configuration --bucket $BUCKET 2>/dev/null | python3 -m json.tool || echo "   No notifications configured"

# ── 3. Create a test PDF ──────────────────────────────────────
echo ""
echo -e "${YELLOW}3. Creating test files...${NC}"

# Minimal valid PDF
cat > /tmp/test-file.pdf << 'EOF'
%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer << /Size 4 /Root 1 0 R >>
startxref
206
%%EOF
EOF
echo "   ✅ Created test-file.pdf"

# Minimal valid PNG (1x1 red pixel)
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82' > /tmp/test-image.png
echo "   ✅ Created test-image.png"

echo "test content" > /tmp/test-file.txt
echo "   ✅ Created test-file.txt (unsupported type)"

# ── 4. Upload to S3 ──────────────────────────────────────────
echo ""
echo -e "${YELLOW}4. Uploading files to S3...${NC}"

echo -e "   ${CYAN}Uploading PDF...${NC}"
$AWS s3 cp /tmp/test-file.pdf s3://$BUCKET/uploads/test-file.pdf
echo -e "   ${GREEN}✅ PDF uploaded${NC}"

echo -e "   ${CYAN}Uploading PNG...${NC}"
$AWS s3 cp /tmp/test-image.png s3://$BUCKET/uploads/test-image.png
echo -e "   ${GREEN}✅ PNG uploaded${NC}"

echo -e "   ${CYAN}Uploading TXT (should be skipped)...${NC}"
$AWS s3 cp /tmp/test-file.txt s3://$BUCKET/uploads/test-file.txt
echo -e "   ${GREEN}✅ TXT uploaded${NC}"

# ── 5. Wait for Lambda processing ────────────────────────────
echo ""
echo -e "${YELLOW}5. Waiting for Lambda chain to execute (5s)...${NC}"
sleep 5

# ── 6. Check Lambda logs ─────────────────────────────────────
echo ""
echo -e "${YELLOW}6. Checking Lambda execution logs...${NC}"

echo -e "   ${CYAN}── file-router logs ──${NC}"
$AWS logs describe-log-groups --query 'logGroups[?contains(logGroupName, `file-router`)].logGroupName' --output text 2>/dev/null | while read -r group; do
    $AWS logs get-log-events \
        --log-group-name "$group" \
        --log-stream-name $($AWS logs describe-log-streams --log-group-name "$group" --query 'logStreams[-1].logStreamName' --output text) \
        --query 'events[].message' --output text 2>/dev/null | head -20
done || echo "   No file-router logs found yet"

echo ""
echo -e "   ${CYAN}── file-processor logs ──${NC}"
$AWS logs describe-log-groups --query 'logGroups[?contains(logGroupName, `file-processor`)].logGroupName' --output text 2>/dev/null | while read -r group; do
    $AWS logs get-log-events \
        --log-group-name "$group" \
        --log-stream-name $($AWS logs describe-log-streams --log-group-name "$group" --query 'logStreams[-1].logStreamName' --output text) \
        --query 'events[].message' --output text 2>/dev/null | head -20
done || echo "   No file-processor logs found yet"

# ── 7. Manually invoke file-processor for verification ────────
echo ""
echo -e "${YELLOW}7. Directly invoking file-processor Lambda (verification)...${NC}"

echo -e "   ${CYAN}Processing PDF...${NC}"
$AWS lambda invoke \
    --function-name file-processor \
    --payload '{"bucket":"file-uploads","key":"uploads/test-file.pdf","size":300,"file_type":"pdf","extension":".pdf","source_lambda":"test-script"}' \
    /tmp/pdf-result.json 2>/dev/null

echo -e "   ${GREEN}PDF Result:${NC}"
python3 -m json.tool /tmp/pdf-result.json 2>/dev/null || cat /tmp/pdf-result.json

echo ""
echo -e "   ${CYAN}Processing PNG...${NC}"
$AWS lambda invoke \
    --function-name file-processor \
    --payload '{"bucket":"file-uploads","key":"uploads/test-image.png","size":68,"file_type":"image","extension":".png","source_lambda":"test-script"}' \
    /tmp/png-result.json 2>/dev/null

echo -e "   ${GREEN}PNG Result:${NC}"
python3 -m json.tool /tmp/png-result.json 2>/dev/null || cat /tmp/png-result.json

# ── 8. List uploaded files ────────────────────────────────────
echo ""
echo -e "${YELLOW}8. Files in S3 bucket:${NC}"
$AWS s3 ls s3://$BUCKET/uploads/ --recursive

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  ✅ Pipeline Test Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  🖥️  Open http://localhost:8080 for the web UI"
echo -e "  📡 LocalStack: http://localhost:4566"
echo ""
