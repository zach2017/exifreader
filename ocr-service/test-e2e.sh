#!/bin/bash
set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ENDPOINT="http://localhost:4566"
UPLOAD_URL="http://localhost:8080/upload"

echo -e "${YELLOW}=== OCR Pipeline E2E Test ===${NC}"

# Wait for services
echo "Waiting for services..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        echo -e "${GREEN}Upload service ready${NC}"
        break
    fi
    sleep 1
done

# Test 1: Create and upload a test text file as an image
echo ""
echo -e "${YELLOW}Test 1: Upload a text image${NC}"

# Create a simple test image with text using ImageMagick (if available)
if command -v convert &> /dev/null; then
    convert -size 400x100 xc:white -font Helvetica -pointsize 24 \
        -draw "text 20,50 'Hello OCR Pipeline Test'" /tmp/test-ocr.png
    RESPONSE=$(curl -sf -F "file=@/tmp/test-ocr.png" "$UPLOAD_URL")
    DOC_ID=$(echo "$RESPONSE" | grep -o '"document_id":"[^"]*"' | cut -d'"' -f4)
    echo -e "  Uploaded image. Document ID: ${GREEN}${DOC_ID}${NC}"
    echo "  Waiting 15s for OCR processing..."
    sleep 15

    # Check results
    echo "  Checking tmp-extracted-text bucket..."
    aws --endpoint-url="$ENDPOINT" s3 ls s3://tmp-extracted-text/ --recursive 2>/dev/null || echo "  (bucket empty or not ready)"
else
    echo -e "  ${YELLOW}Skipping (ImageMagick not installed)${NC}"
fi

# Test 2: Create and upload a simple text file pretending to be RTF
echo ""
echo -e "${YELLOW}Test 2: Upload an RTF file${NC}"
cat > /tmp/test.rtf << 'EOF'
{\rtf1\ansi
Hello this is a test RTF document for the OCR pipeline.
It contains simple text that should be extracted.
}
EOF
RESPONSE=$(curl -sf -F "file=@/tmp/test.rtf" "$UPLOAD_URL")
DOC_ID=$(echo "$RESPONSE" | grep -o '"document_id":"[^"]*"' | cut -d'"' -f4)
echo -e "  Uploaded RTF. Document ID: ${GREEN}${DOC_ID}${NC}"
echo "  Waiting 10s for text extraction..."
sleep 10

echo "  Checking extracted-text bucket..."
aws --endpoint-url="$ENDPOINT" s3 ls s3://extracted-text/ --recursive 2>/dev/null || echo "  (bucket empty or not ready)"

# Summary
echo ""
echo -e "${YELLOW}=== Bucket Contents ===${NC}"
echo ""
echo "uploads:"
aws --endpoint-url="$ENDPOINT" s3 ls s3://uploads/ --recursive 2>/dev/null || echo "  (empty)"
echo ""
echo "extracted-text:"
aws --endpoint-url="$ENDPOINT" s3 ls s3://extracted-text/ --recursive 2>/dev/null || echo "  (empty)"
echo ""
echo "tmp-files:"
aws --endpoint-url="$ENDPOINT" s3 ls s3://tmp-files/ --recursive 2>/dev/null || echo "  (empty)"
echo ""
echo "tmp-extracted-text:"
aws --endpoint-url="$ENDPOINT" s3 ls s3://tmp-extracted-text/ --recursive 2>/dev/null || echo "  (empty)"

echo ""
echo -e "${GREEN}=== Test complete ===${NC}"
