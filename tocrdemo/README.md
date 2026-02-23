# S3 → Lambda → Lambda Pipeline (LocalStack + Docker)

Everything runs locally in Docker. No AWS account needed.

## Architecture

```
Browser ──PUT──▸ S3 (file-uploads) ──event──▸ λ file-router ──invoke──▸ λ file-processor
                   │                              │                         │
                   │ LocalStack container          │ Classifies file         │ Downloads from S3
                   │ port 4566                     │ PDF or image? →         │ Extracts metadata
                   │                               │ Invoke Lambda 2         │ Returns results
```

### Docker Services

| Service | Purpose |
|---------|---------|
| `localstack` | Emulates S3, Lambda, IAM, CloudWatch |
| `setup` | One-shot: creates bucket, deploys Lambdas, wires S3 events |
| `frontend` | Nginx: serves HTML + proxies API calls to LocalStack |

### Lambda Functions (running on LocalStack)

| Function | Trigger | Action |
|----------|---------|--------|
| `file-router` | S3 `ObjectCreated` event | Checks extension → invokes `file-processor` for PDF/images |
| `file-processor` | Invoked by `file-router` via `boto3` | Downloads file from S3, extracts size/dimensions/pages |

## Quick Start

```bash
# Start everything (LocalStack + setup + frontend)
docker compose up -d

# Watch the setup container provision resources
docker logs -f localstack-setup

# Open the upload UI
open http://localhost:8080
```

The `setup` container waits for LocalStack to be healthy, then:
1. Creates `file-uploads` S3 bucket with CORS
2. Packages and deploys both Lambda functions
3. Wires S3 event notification → `file-router`

### Verify with CLI

```bash
chmod +x test-pipeline.sh
./test-pipeline.sh
```

## How Lambda-to-Lambda Invocation Works

`file-router` calls `file-processor` using **boto3 direct invocation**:

```python
import boto3, json

lambda_client = boto3.client('lambda', endpoint_url='http://localhost:4566', ...)

# Synchronous — wait for result
response = lambda_client.invoke(
    FunctionName='file-processor',         # target Lambda
    InvocationType='RequestResponse',      # sync (or 'Event' for async)
    Payload=json.dumps({
        'bucket': 'file-uploads',
        'key': 'uploads/photo.png',
        'file_type': 'image',
        'extension': '.png',
    }),
)
result = json.loads(response['Payload'].read())
```

### Three Invocation Patterns

| Pattern | How | Best For |
|---------|-----|----------|
| **Direct (boto3)** | `lambda.invoke()` — sync or async | Simple chains, low latency |
| **Step Functions** | State machine orchestration | Complex workflows, retries, parallel |
| **SNS/SQS** | Pub/sub or queue | Fan-out, decoupling, dead-letter queues |

## Project Structure

```
├── docker-compose.yml      # 3 services: localstack, setup, frontend
├── setup/
│   ├── Dockerfile          # Python + AWS CLI + zip
│   └── provision.sh        # Creates all AWS resources on LocalStack
├── lambdas/
│   ├── file_router.py      # λ1: S3 event → classify → invoke λ2
│   └── file_processor.py   # λ2: download from S3 → extract metadata
├── html/
│   └── index.html          # Upload UI (drag & drop)
├── nginx-conf/
│   └── default.conf        # Proxy /api/s3 and /api/lambda to LocalStack
└── test-pipeline.sh        # CLI smoke test
```

## Useful Commands

```bash
# Alias for convenience
alias awslocal='aws --endpoint-url=http://localhost:4566 --region=us-east-1'

# List resources
awslocal s3 ls
awslocal lambda list-functions --query 'Functions[].FunctionName'

# Upload a file
awslocal s3 cp myfile.pdf s3://file-uploads/uploads/myfile.pdf

# Invoke Lambda directly
awslocal lambda invoke --function-name file-processor \
  --payload '{"bucket":"file-uploads","key":"uploads/myfile.pdf","file_type":"pdf","extension":".pdf","source_lambda":"cli"}' \
  result.json && cat result.json | python3 -m json.tool

# View logs
docker logs localstack 2>&1 | grep "file-processor\|file-router"

# Rebuild after Lambda code changes
docker compose up -d --build setup
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Setup fails | `docker logs localstack-setup` — check for errors |
| Lambda not found | Wait for setup to complete: `docker logs -f localstack-setup` |
| CORS errors | Use port 8080 (Nginx proxy), not 4566 directly |
| S3 notification not firing | `awslocal s3api get-bucket-notification-configuration --bucket file-uploads` |
| Rebuild Lambdas | `docker compose up -d --build setup` |
