#!/bin/bash
# ============================================================
# Test Upload Script
# Uploads sample files to S3 and verifies the Lambda pipeline.
# Run after: docker compose up -d (wait for setup to finish)
#
# Usage:
#   chmod +x test-upload.sh
#   ./test-upload.sh
# ============================================================

set -euo pipefail

EP="http://localhost:4566"
BUCKET="file-uploads"

# Colors
G='\033[0;32m' R='\033[0;31m' Y='\033[1;33m' C='\033[0;36m' B='\033[1m' N='\033[0m'

PASS=0
FAIL=0

pass() { echo -e "  ${G}PASS${N} $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${R}FAIL${N} $1"; FAIL=$((FAIL+1)); }

aws_cmd() {
    aws --endpoint-url="$EP" --region=us-east-1  "$@"
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SAMPLES="$SCRIPT_DIR/test-samples"

echo ""
echo -e "${B}══════════════════════════════════════════════${N}"
echo -e "${B}  S3 → Lambda Pipeline Test${N}"
echo -e "${B}══════════════════════════════════════════════${N}"

# ── 1. Check LocalStack is running ──
echo ""
echo -e "${C}[1/7] Checking LocalStack...${N}"
if curl -sf "$EP/_localstack/health" > /dev/null 2>&1; then
    pass "LocalStack is running"
else
    fail "LocalStack not reachable at $EP"
    echo -e "${R}  Make sure you ran: docker compose up -d${N}"
    exit 1
fi

# ── 2. Check S3 bucket exists ──
echo ""
echo -e "${C}[2/7] Checking S3 bucket...${N}"
if aws_cmd s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    pass "Bucket '$BUCKET' exists"
else
    fail "Bucket '$BUCKET' not found"
    echo -e "${R}  Wait for setup to finish: docker logs -f localstack-setup${N}"
    exit 1
fi

# ── 3. Check Lambda functions ──
echo ""
echo -e "${C}[3/7] Checking Lambda functions...${N}"
LAMBDAS=$(aws_cmd lambda list-functions --query 'Functions[].FunctionName' --output text 2>/dev/null)
if echo "$LAMBDAS" | grep -q "file-router"; then
    pass "Lambda 'file-router' deployed"
else
    fail "Lambda 'file-router' not found"
fi
if echo "$LAMBDAS" | grep -q "file-processor"; then
    pass "Lambda 'file-processor' deployed"
else
    fail "Lambda 'file-processor' not found"
fi

# ── 4. Check sample files exist ──
echo ""
echo -e "${C}[4/7] Checking sample files...${N}"
if [ ! -d "$SAMPLES" ]; then
    fail "test-samples/ directory not found at $SAMPLES"
    echo "  Creating sample files on the fly..."
    mkdir -p "$SAMPLES"

    # Minimal PDF
    cat > "$SAMPLES/sample.pdf" << 'PDFEOF'
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
PDFEOF

    # Minimal PNG (1x1)
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB\x60\x82' > "$SAMPLES/sample.png"

    echo "hello world" > "$SAMPLES/sample.txt"
    echo "  Created fallback samples"
fi

for f in sample.pdf sample.png sample.txt; do
    if [ -f "$SAMPLES/$f" ]; then
        SIZE=$(wc -c < "$SAMPLES/$f")
        pass "$f exists ($SIZE bytes)"
    else
        fail "$f missing"
    fi
done
# Also check for jpg if it exists
if [ -f "$SAMPLES/sample.jpg" ]; then
    SIZE=$(wc -c < "$SAMPLES/sample.jpg")
    pass "sample.jpg exists ($SIZE bytes)"
fi

# ── 5. Upload files to S3 ──
echo ""
echo -e "${C}[5/7] Uploading files to S3...${N}"

upload_file() {
    local filepath="$1"
    local filename=$(basename "$filepath")
    local s3key="uploads/test-$filename"

    if aws_cmd s3 cp "$filepath" "s3://$BUCKET/$s3key" --quiet 2>/dev/null; then
        pass "Uploaded $filename → s3://$BUCKET/$s3key"
    else
        fail "Failed to upload $filename"
    fi
}

for f in "$SAMPLES"/sample.*; do
    [ -f "$f" ] && upload_file "$f"
done

echo ""
echo "  Waiting 3s for S3 event notifications..."
sleep 3

# ── 6. Invoke Lambdas directly and verify results ──
echo ""
echo -e "${C}[6/7] Testing Lambda invocations...${N}"

# Test 1: file-processor with PDF
echo ""
echo -e "  ${Y}── Test: file-processor (PDF) ──${N}"
RESULT=$(aws_cmd lambda invoke \
    --function-name file-processor \
    --payload '{"bucket":"file-uploads","key":"uploads/test-sample.pdf","size":867,"file_type":"pdf","extension":".pdf","source_lambda":"test-script"}' \
    /dev/stdout 2>/dev/null)

STATUS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "error")
if [ "$STATUS" = "success" ]; then
    pass "file-processor handled PDF"
    echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
pr = d.get('processing_result', {})
print(f'      Processor:  {pr.get(\"processor\",\"?\")}')
print(f'      Size:       {pr.get(\"formatted_size\",\"?\")}')
print(f'      Pages:      {pr.get(\"page_count\",\"?\")}')
print(f'      PDF Ver:    {pr.get(\"pdf_version\",\"?\")}')
print(f'      Encrypted:  {pr.get(\"encrypted\",\"?\")}')
" 2>/dev/null || true
else
    fail "file-processor failed on PDF (status=$STATUS)"
    echo "  $RESULT" | head -5
fi

# Test 2: file-processor with PNG
echo ""
echo -e "  ${Y}── Test: file-processor (PNG) ──${N}"
RESULT=$(aws_cmd lambda invoke \
    --function-name file-processor \
    --payload '{"bucket":"file-uploads","key":"uploads/test-sample.png","size":123,"file_type":"image","extension":".png","source_lambda":"test-script"}' \
    /dev/stdout 2>/dev/null)

STATUS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "error")
if [ "$STATUS" = "success" ]; then
    pass "file-processor handled PNG"
    echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
pr = d.get('processing_result', {})
print(f'      Processor:  {pr.get(\"processor\",\"?\")}')
print(f'      Size:       {pr.get(\"formatted_size\",\"?\")}')
print(f'      Dimensions: {pr.get(\"dimensions\",\"?\")}')
if 'megapixels' in pr:
    print(f'      Megapixels: {pr.get(\"megapixels\",\"?\")}')
" 2>/dev/null || true
else
    fail "file-processor failed on PNG (status=$STATUS)"
fi

# Test 3: file-processor with JPG (if sample exists)
if [ -f "$SAMPLES/sample.jpg" ]; then
    echo ""
    echo -e "  ${Y}── Test: file-processor (JPG) ──${N}"
    RESULT=$(aws_cmd lambda invoke \
        --function-name file-processor \
        --payload '{"bucket":"file-uploads","key":"uploads/test-sample.jpg","size":175,"file_type":"image","extension":".jpg","source_lambda":"test-script"}' \
        /dev/stdout 2>/dev/null)

    STATUS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "error")
    if [ "$STATUS" = "success" ]; then
        pass "file-processor handled JPG"
    else
        fail "file-processor failed on JPG"
    fi
fi

# Test 4: file-router full pipeline (S3 event → classify → invoke processor)
echo ""
echo -e "  ${Y}── Test: file-router full chain (PDF) ──${N}"
RESULT=$(aws_cmd lambda invoke \
    --function-name file-router \
    --payload '{"Records":[{"s3":{"bucket":{"name":"file-uploads"},"object":{"key":"uploads/test-sample.pdf","size":867}}}]}' \
    /dev/stdout 2>/dev/null)

PROCESSED=$(echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
body = json.loads(d.get('body','{}'))
print(body.get('files_processed', 0))
" 2>/dev/null || echo "0")
if [ "$PROCESSED" = "1" ]; then
    pass "file-router → file-processor chain works (1 file processed)"
else
    fail "file-router chain failed (processed=$PROCESSED)"
    echo "  $RESULT" | head -5
fi

# Test 5: file-router with unsupported file (should skip)
echo ""
echo -e "  ${Y}── Test: file-router skip (.txt) ──${N}"
RESULT=$(aws_cmd lambda invoke \
    --function-name file-router \
    --payload '{"Records":[{"s3":{"bucket":{"name":"file-uploads"},"object":{"key":"uploads/test-sample.txt","size":100}}}]}' \
    /dev/stdout 2>/dev/null)

SKIPPED=$(echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
body = json.loads(d.get('body','{}'))
print(body.get('files_skipped', 0))
" 2>/dev/null || echo "0")
if [ "$SKIPPED" = "1" ]; then
    pass "file-router correctly skipped .txt file"
else
    fail "file-router should have skipped .txt (skipped=$SKIPPED)"
fi

# ── 7. List everything in S3 ──
echo ""
echo -e "${C}[7/7] S3 bucket contents...${N}"
aws_cmd s3 ls "s3://$BUCKET/uploads/" 2>/dev/null | sed 's/^/  /' || echo "  (empty or error)"

# ── Summary ──
echo ""
echo -e "${B}══════════════════════════════════════════════${N}"
TOTAL=$((PASS+FAIL))
if [ "$FAIL" -eq 0 ]; then
    echo -e "${G}  ALL $TOTAL TESTS PASSED${N}"
else
    echo -e "${R}  $FAIL/$TOTAL TESTS FAILED${N}"
fi
echo -e "${B}══════════════════════════════════════════════${N}"
echo ""
echo "  Upload UI:  http://localhost:8080"
echo "  LocalStack: http://localhost:4566"
echo ""

exit $FAIL
