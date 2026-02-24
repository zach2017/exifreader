# S3 → Lambda → Lambda Pipeline (LocalStack + Docker)

Everything runs locally in Docker. No AWS account needed.

## Quick Start

```bash
# 1. Start everything
docker compose up -d --build

# 2. Watch setup provision resources (wait for "ALL RESOURCES PROVISIONED")
docker logs -f localstack-setup

# 3. Run the test suite
chmod +x test-upload.sh
./test-upload.sh

# 4. Open the upload UI
open http://localhost:8080
```

## Clean Restart

```bash
docker compose down -v
docker compose up -d --build
```

The setup service automatically:
- **Deletes** any existing buckets, lambdas, and IAM roles
- **Creates** fresh S3 bucket, deploys both lambdas, wires S3 event notifications
- Verifies everything is clean and working

## Architecture

```
Browser ──PUT──▸ S3 (file-uploads) ──event──▸ λ file-router ──invoke──▸ λ file-processor
                                                  │                         │
                                                  │ PDF/image? →            │ Downloads from S3
                                                  │ Invoke Lambda 2         │ Returns metadata
                                                  │ Other? → Skip           │ (size, dims, pages)
```

## Project Structure

```
├── docker-compose.yml        # 3 services: localstack, setup, frontend
├── setup/
│   └── Dockerfile            # Provision script baked in (no Windows CRLF issues)
├── lambdas/
│   ├── file_router.py        # λ1: S3 event → classify → invoke λ2
│   └── file_processor.py     # λ2: download from S3 → extract metadata
├── html/
│   └── index.html            # Drag & drop upload UI
├── nginx-conf/
│   └── default.conf          # Proxy /api/* to LocalStack
├── test-samples/             # Sample files for testing
│   ├── sample.pdf            # 2-page PDF
│   ├── sample.png            # 16x16 gradient PNG
│   ├── sample.jpg            # 32x32 JPEG
│   └── sample.txt            # Text file (should be skipped)
└── test-upload.sh            # Automated test script
```

## Test Script

```bash
./test-upload.sh
```

Runs 8+ checks: verifies LocalStack health, bucket exists, lambdas deployed,
uploads all sample files, invokes each lambda directly, tests the full
file-router → file-processor chain, and confirms .txt files are skipped.

## Lambda-to-Lambda Invocation

```python
response = lambda_client.invoke(
    FunctionName='file-processor',
    InvocationType='RequestResponse',   # sync (or 'Event' for fire-and-forget)
    Payload=json.dumps(payload),
)
result = json.loads(response['Payload'].read())
```
