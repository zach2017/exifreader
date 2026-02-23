# S3 → Lambda → Lambda Pipeline (LocalStack)

A complete local AWS development environment using Docker + LocalStack that demonstrates:

- **S3 bucket** creation and browser-based file uploads
- **S3 event notifications** triggering Lambda functions
- **Lambda-to-Lambda invocation** (the core pattern)
- **File processing** (PDF metadata, image dimensions, file size)

---

## Architecture

```
┌──────────┐     PUT      ┌──────────────┐   S3 Event    ┌──────────────┐
│  Browser  │ ──────────▸  │  S3 Bucket   │ ────────────▸ │  Lambda 1    │
│  (HTML)   │              │ file-uploads │  Notification  │ file-router  │
└──────────┘              └──────────────┘               └──────┬───────┘
                                                                │
                                                    boto3.invoke│(if PDF/image)
                                                                │
                                                         ┌──────▼───────┐
                                                         │  Lambda 2    │
                                                         │file-processor│
                                                         │              │
                                                         │ • Downloads  │
                                                         │   from S3    │
                                                         │ • Extracts   │
                                                         │   metadata   │
                                                         └──────────────┘
```

### Flow

1. **User uploads a file** via the HTML frontend → S3 `PUT` to `file-uploads` bucket
2. **S3 event notification** fires `s3:ObjectCreated:*` → triggers **Lambda 1** (`file-router`)
3. **Lambda 1** checks the file extension:
   - PDF or image → **invokes Lambda 2** (`file-processor`) via `boto3`
   - Other types → skips (logged)
4. **Lambda 2** pulls the file from S3 using the bucket/key from the payload, then:
   - **Images**: extracts dimensions (width × height) from binary headers
   - **PDFs**: extracts page count, PDF version, encryption status
   - Returns the processed metadata to Lambda 1

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- AWS CLI (optional, for manual testing)

### 1. Start the Stack

```bash
# Clone/copy this project, then:
cd localstack-s3-lambda

# Make init script executable
chmod +x init-aws.sh test-pipeline.sh

# Start everything
docker compose up -d
```

LocalStack will automatically:
- Create the S3 bucket (`file-uploads`)
- Deploy both Lambda functions
- Configure S3 event notifications

### 2. Open the Web UI

```
http://localhost:8080
```

Drag & drop files (PDFs, images) to upload. The UI shows real-time processing results from the Lambda chain.

### 3. Run the Test Script (optional)

```bash
./test-pipeline.sh
```

This creates test PDF/PNG files, uploads them, and shows the Lambda processing results.

---

## How to Call a Lambda from Another Lambda

This is the core pattern. There are **3 main approaches**:

### Method 1: Direct Invocation via AWS SDK (Used Here)

The simplest and most common approach. Lambda 1 uses `boto3` to invoke Lambda 2.

```python
import boto3
import json

lambda_client = boto3.client('lambda')

# ── Synchronous (wait for response) ─────────────────────
response = lambda_client.invoke(
    FunctionName='file-processor',      # Target Lambda name or ARN
    InvocationType='RequestResponse',   # Sync: blocks until complete
    Payload=json.dumps({                # JSON payload
        'bucket': 'my-bucket',
        'key': 'file.pdf',
        'file_type': 'pdf',
    }),
)

# Read the response
result = json.loads(response['Payload'].read().decode('utf-8'))
print(result)

# ── Asynchronous (fire and forget) ──────────────────────
response = lambda_client.invoke(
    FunctionName='file-processor',
    InvocationType='Event',             # Async: returns immediately (HTTP 202)
    Payload=json.dumps({...}),
)
# No response payload — Lambda 2 runs in background
```

**InvocationType options:**

| Type | Behavior | Use Case |
|------|----------|----------|
| `RequestResponse` | Synchronous — waits for result | Need the result immediately |
| `Event` | Asynchronous — fire & forget | Background processing, don't need result |
| `DryRun` | Validates parameters only | Testing/debugging |

### Method 2: AWS Step Functions (State Machines)

Best for complex multi-step workflows with retry logic, parallel execution, and error handling.

```json
{
  "StartAt": "RouteFile",
  "States": {
    "RouteFile": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:000000000000:function:file-router",
      "Next": "ProcessFile"
    },
    "ProcessFile": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:000000000000:function:file-processor",
      "End": true,
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3
        }
      ]
    }
  }
}
```

### Method 3: SNS/SQS (Decoupled)

Best for fan-out patterns where multiple Lambdas need to process the same event.

```python
# Publisher Lambda
sns_client = boto3.client('sns')
sns_client.publish(
    TopicArn='arn:aws:sns:us-east-1:000000000000:file-events',
    Message=json.dumps({'bucket': 'my-bucket', 'key': 'file.pdf'}),
)

# Multiple Lambdas can subscribe to the same SNS topic
```

### Comparison

| Approach | Coupling | Latency | Retry | Fan-out | Complexity |
|----------|----------|---------|-------|---------|------------|
| **Direct (boto3)** | Tight | Low | Manual | No | Low |
| **Step Functions** | Orchestrated | Medium | Built-in | Yes (parallel) | Medium |
| **SNS/SQS** | Loose | Higher | Built-in (SQS) | Yes | Medium |

---

## Project Structure

```
localstack-s3-lambda/
├── docker-compose.yml          # LocalStack + Nginx containers
├── init-aws.sh                 # Auto-creates S3, Lambdas, notifications
├── test-pipeline.sh            # CLI test script
├── frontend/
│   ├── index.html              # Upload UI (drag & drop)
│   └── nginx.conf              # Reverse proxy to LocalStack
└── lambdas/
    ├── file_router.py          # Lambda 1: S3 event → classify → invoke L2
    └── file_processor.py       # Lambda 2: Download from S3, extract metadata
```

---

## Manual AWS CLI Commands

```bash
# Set alias for convenience
alias awslocal='aws --endpoint-url=http://localhost:4566 --region=us-east-1'

# List S3 buckets
awslocal s3 ls

# Upload a file
awslocal s3 cp myfile.pdf s3://file-uploads/uploads/myfile.pdf

# List Lambda functions
awslocal lambda list-functions

# Invoke Lambda directly
awslocal lambda invoke \
  --function-name file-processor \
  --payload '{"bucket":"file-uploads","key":"uploads/myfile.pdf","file_type":"pdf","extension":".pdf","source_lambda":"manual"}' \
  output.json && cat output.json | python3 -m json.tool

# Check S3 event notification config
awslocal s3api get-bucket-notification-configuration --bucket file-uploads

# View Lambda logs
awslocal logs describe-log-groups
awslocal logs get-log-events \
  --log-group-name /aws/lambda/file-router \
  --log-stream-name $(awslocal logs describe-log-streams \
    --log-group-name /aws/lambda/file-router \
    --query 'logStreams[-1].logStreamName' --output text)
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| LocalStack not starting | Check Docker daemon is running: `docker ps` |
| Lambdas not created | Check init logs: `docker logs localstack` |
| CORS errors in browser | Use the Nginx proxy (port 8080), not direct LocalStack (4566) |
| Lambda timeout | Increase timeout in `init-aws.sh` (default: 60s) |
| S3 notification not firing | Verify: `awslocal s3api get-bucket-notification-configuration --bucket file-uploads` |

---

## Extending This

- **Add Step Functions**: Orchestrate a multi-step pipeline (e.g., validate → process → store results)
- **Add SQS Dead Letter Queue**: Catch failed Lambda invocations
- **Add DynamoDB**: Store processing results in a table
- **Add SNS notifications**: Send email/SMS when processing completes
- **Add API Gateway**: Create REST endpoints in front of Lambdas
