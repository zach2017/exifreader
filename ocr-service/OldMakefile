.PHONY: up down logs build clean test-upload

# Start all services
up: build
	docker-compose up -d
	@echo ""
	@echo "=== Services starting ==="
	@echo "Upload UI:  http://localhost:8080"
	@echo "LocalStack: http://localhost:4566"
	@echo ""
	@echo "Run 'make logs' to watch processing"

# Build all images
build:
	docker-compose build

# Stop all services
down:
	docker-compose down -v

# Follow logs from all services
logs:
	docker-compose logs -f

# Logs for individual services
logs-upload:
	docker-compose logs -f upload-service

logs-extract:
	docker-compose logs -f text-extract-service

logs-ocr:
	docker-compose logs -f ocr-service

logs-localstack:
	docker-compose logs -f localstack

# Clean everything
clean:
	docker-compose down -v --rmi all

# Check S3 buckets
list-buckets:
	aws --endpoint-url=http://localhost:4566 s3 ls

# Check extracted text
list-extracted:
	aws --endpoint-url=http://localhost:4566 s3 ls s3://extracted-text/ --recursive

# Check OCR extracted text
list-ocr:
	aws --endpoint-url=http://localhost:4566 s3 ls s3://tmp-extracted-text/ --recursive

# Check uploads
list-uploads:
	aws --endpoint-url=http://localhost:4566 s3 ls s3://uploads/ --recursive

# Check SQS queue status
check-queues:
	@echo "--- file-processing ---"
	@aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
		--queue-url http://localhost:4566/000000000000/file-processing \
		--attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible 2>/dev/null || echo "Queue not ready"
	@echo "--- ocr-processing ---"
	@aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
		--queue-url http://localhost:4566/000000000000/ocr-processing \
		--attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible 2>/dev/null || echo "Queue not ready"
	@echo "--- ocr-complete ---"
	@aws --endpoint-url=http://localhost:4566 sqs get-queue-attributes \
		--queue-url http://localhost:4566/000000000000/ocr-complete \
		--attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible 2>/dev/null || echo "Queue not ready"

# Download extracted text for a document
# Usage: make get-text DOC_ID=<uuid>
get-text:
	aws --endpoint-url=http://localhost:4566 s3 cp s3://extracted-text/$(DOC_ID).txt -

# Download OCR text for a document
get-ocr-text:
	aws --endpoint-url=http://localhost:4566 s3 cp s3://tmp-extracted-text/$(DOC_ID).txt -

# Test upload via curl
test-pdf:
	@echo "Uploading test PDF..."
	curl -F "file=@test.pdf" http://localhost:8080/upload

test-image:
	@echo "Uploading test image..."
	curl -F "file=@test.png" http://localhost:8080/upload
