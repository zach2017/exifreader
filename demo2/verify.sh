#!/bin/bash
# ──────────────────────────────────────────────────
#  Verify the OCR Extract stack is fully operational
# ──────────────────────────────────────────────────
set -e

ENDPOINT="http://localhost:4566"
BACKEND="http://localhost:5000"
FUNC="ocr-extract"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════"
echo "  OCR Extract — Health Check"
echo "═══════════════════════════════════════════════"

# 1. LocalStack reachable?
echo ""
echo "1. LocalStack"
if curl -sf "$ENDPOINT/_localstack/health" > /dev/null 2>&1; then
    pass "LocalStack reachable at $ENDPOINT"
    HEALTH=$(curl -sf "$ENDPOINT/_localstack/health")
    LAMBDA_SVC=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('services',{}).get('lambda','?'))" 2>/dev/null || echo "?")
    if [ "$LAMBDA_SVC" = "running" ] || [ "$LAMBDA_SVC" = "available" ]; then
        pass "Lambda service: $LAMBDA_SVC"
    else
        warn "Lambda service: $LAMBDA_SVC"
    fi
else
    fail "LocalStack not reachable. Is it running?"
    exit 1
fi

# 2. Lambda function exists and is Active?
echo ""
echo "2. Lambda Function"
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
FUNC_INFO=$(aws --endpoint-url=$ENDPOINT lambda get-function --function-name "$FUNC" 2>&1) || true
if echo "$FUNC_INFO" | grep -q "FunctionName"; then
    pass "Function '$FUNC' exists"
    STATE=$(echo "$FUNC_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['Configuration']['State'])" 2>/dev/null || echo "?")
    if [ "$STATE" = "Active" ]; then
        pass "State: Active"
    else
        fail "State: $STATE (expected Active)"
    fi
else
    fail "Function '$FUNC' NOT FOUND"
    echo ""
    echo "  Available functions:"
    aws --endpoint-url=$ENDPOINT lambda list-functions \
        --query 'Functions[].FunctionName' --output text 2>/dev/null || echo "  (none)"
fi

# 3. Docker image exists?
echo ""
echo "3. Lambda Docker Image"
if docker image inspect lambda-ocr-python311 > /dev/null 2>&1; then
    pass "Image 'lambda-ocr-python311' exists"
else
    fail "Image 'lambda-ocr-python311' not found — run: docker compose build lambda-image"
fi

# 4. Backend reachable?
echo ""
echo "4. Backend"
HEALTH_RESP=$(curl -sf "$BACKEND/api/health" 2>/dev/null) || true
if [ -n "$HEALTH_RESP" ]; then
    pass "Backend reachable at $BACKEND"
    LAMBDA_STATE=$(echo "$HEALTH_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('lambda_state','?'))" 2>/dev/null || echo "?")
    pass "Backend sees Lambda state: $LAMBDA_STATE"
else
    fail "Backend not reachable"
fi

# 5. Frontend reachable?
echo ""
echo "5. Frontend"
if curl -sf "http://localhost:8080" > /dev/null 2>&1; then
    pass "Frontend reachable at http://localhost:8080"
else
    fail "Frontend not reachable"
fi

echo ""
echo "═══════════════════════════════════════════════"
