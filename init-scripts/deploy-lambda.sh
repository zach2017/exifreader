#!/bin/bash
# Deploy the OCR Lambda function to LocalStack (backup — backend also auto-deploys)

echo "=== [init] Deploying OCR Lambda ==="

FUNCTION_NAME="ocr-extract-text"
LAMBDA_SRC="/etc/localstack/init/ready.d/lambda_src"
ZIP_PATH="/tmp/ocr_lambda.zip"
MAX_RETRIES=5

# Check if already exists
existing=$(awslocal lambda get-function --function-name "$FUNCTION_NAME" 2>&1)
if echo "$existing" | grep -q '"FunctionName"'; then
    echo "=== [init] Lambda '$FUNCTION_NAME' already exists, skipping ==="
    exit 0
fi

# Build the zip
if [ ! -f "$LAMBDA_SRC/handler.py" ]; then
    echo "=== [init] ERROR: handler.py not found at $LAMBDA_SRC/handler.py ==="
    ls -la "$LAMBDA_SRC/" 2>/dev/null || echo "(directory not found)"
    echo "=== [init] Skipping — backend will auto-deploy ==="
    exit 0
fi

cd "$LAMBDA_SRC"
rm -f "$ZIP_PATH"
zip -j "$ZIP_PATH" handler.py
echo "=== [init] Built zip ($(stat -c%s "$ZIP_PATH" 2>/dev/null || echo '?') bytes) ==="

# Create with retries
for i in $(seq 1 $MAX_RETRIES); do
    echo "=== [init] Attempt $i/$MAX_RETRIES ==="

    result=$(awslocal lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --handler handler.handler \
        --zip-file "fileb://$ZIP_PATH" \
        --role arn:aws:iam::000000000000:role/lambda-role \
        --timeout 60 \
        --memory-size 512 2>&1)

    if echo "$result" | grep -q '"FunctionName"'; then
        echo "=== [init] Lambda created successfully ==="

        # Wait for Active
        for j in $(seq 1 10); do
            state=$(awslocal lambda get-function --function-name "$FUNCTION_NAME" 2>&1 | grep -o '"State": "[^"]*"' | head -1)
            echo "=== [init] State: $state ==="
            if echo "$state" | grep -q "Active"; then
                break
            fi
            sleep 2
        done

        # Smoke test
        echo "=== [init] Smoke test ==="
        awslocal lambda invoke \
            --function-name "$FUNCTION_NAME" \
            --payload '{"image_b64":"","image_ext":"png","image_name":"test"}' \
            /tmp/lambda_smoke.json 2>&1 || true
        cat /tmp/lambda_smoke.json 2>/dev/null
        echo ""
        echo "=== [init] Done ==="
        exit 0
    fi

    if echo "$result" | grep -q "ResourceConflictException\|already exist"; then
        echo "=== [init] Function already exists (race condition), done ==="
        exit 0
    fi

    echo "=== [init] Failed: $result ==="
    sleep 3
done

echo "=== [init] All retries exhausted — backend will auto-deploy ==="
exit 0
