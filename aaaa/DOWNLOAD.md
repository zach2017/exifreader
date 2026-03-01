# OCR Lambda — Download & Quickstart

This file explains what the program does, its dependencies, and how to download/install and run it locally for development and testing.

## What this program does
- Runs as an AWS Lambda that responds to S3 create-object events.
- Downloads an image from S3, runs Tesseract OCR on it, uploads a `.txt` result to the `ocr-output` bucket, and sends an SQS message to `ocr-results` with metadata.
- Main orchestration code: `lambda/main.go`.

## High-level flow
1. Lambda handler `handleS3Event` receives an S3 event and iterates records.
2. For each image record, `OCRProcessor.ProcessImage` is called.
3. `ProcessImage` downloads the object, runs `tesseract` (external binary), reads the text output, uploads the `.txt` to S3, and sends an SQS message.
4. Empty OCR results are skipped (no upload or SQS message).

## Important files
- [lambda/main.go](lambda/main.go)
- [lambda/go.mod](lambda/go.mod)
- This file: [DOWNLOAD.md](DOWNLOAD.md)

## Go dependencies (what they do)
- `github.com/aws/aws-lambda-go` — Lambda handler utilities and typed event models (S3 event, etc.).
- `github.com/aws/aws-sdk-go-v2` and subpackages:
  - `config` — load SDK config (region, endpoint, credentials).
  - `credentials` — create static creds (used for local emulators).
  - `service/s3` — S3 client (`GetObject`, `PutObject`).
  - `service/sqs` — SQS client (`GetQueueUrl`, `SendMessage`).
- Indirect packages are internal SDK helpers pulled automatically by `go`.

## External dependencies (non-Go)
- Tesseract OCR CLI must be installed on the runtime. The program executes `tesseract` and reads the generated `<base>.txt` file.
- AWS services: S3 and SQS in production.
- For local testing you can use LocalStack (S3 + SQS), MinIO (S3-compatible), or any SQS emulator.

## Environment variables / configuration
- `AWS_ENDPOINT_URL` (optional): when set, `NewOCRProcessor` uses it as the endpoint and creates static credentials. Useful with LocalStack/MinIO (e.g., `http://localhost:4566`).
- `AWS_DEFAULT_REGION` (optional): defaults to `us-east-1`.

## Install Tesseract
Choose the command for your OS.

- Ubuntu/Debian:
```bash
sudo apt update
sudo apt install -y tesseract-ocr libtesseract-data
```
- Amazon Linux 2 (container / Lambda build image):
```bash
yum install -y epel-release
yum install -y tesseract
```
- macOS (Homebrew):
```bash
brew install tesseract
```
- Windows (Chocolatey):
```powershell
choco install -y tesseract
```
Or download official Windows installer from the Tesseract project.

Note: For Lambda, include Tesseract in the deployment package or use a Lambda layer or container image that contains the `tesseract` binary.

## Build the Go binary locally
1. Ensure Go 1.22 (or compatible) is installed.
2. From the `lambda` folder build the binary:
```bash
cd lambda
go build -o ocr-lambda
```

## Run locally with LocalStack (integration test)
1. Start LocalStack (or run `localstack` Docker container exposing S3 and SQS).
2. Export env vars for the endpoint and region:
```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_DEFAULT_REGION=us-east-1
```
3. Create buckets and queue in LocalStack (example using AWS CLI configured for LocalStack):
```bash
aws --endpoint-url=http://localhost:4566 s3 mb s3://my-source-bucket
aws --endpoint-url=http://localhost:4566 s3 mb s3://ocr-output
aws --endpoint-url=http://localhost:4566 sqs create-queue --queue-name ocr-results
```
4. Upload an image to `my-source-bucket` and call `ProcessImage` manually from a small test harness or invoke the built Lambda container.

## Docker / Lambda container notes
- If using Docker for local runs or a Lambda container, make sure the container image contains the `tesseract` binary.
- The `tmp` directory used is `/tmp` (writable in Lambda and most containers).

## Running in AWS Lambda (production)
- Package the binary or container image and deploy to Lambda.
- Ensure the Lambda execution role has permissions:
  - `s3:GetObject` on source buckets
  - `s3:PutObject` on `ocr-output`
  - `sqs:SendMessage` and `sqs:GetQueueUrl` on the queue
- Create the SQS queue `ocr-results` beforehand (or adjust code to accept queue URL via env var if you prefer).

## Unit testing tips
- `S3Client` and `SQSClient` are defined as small interfaces — implement mocks for unit tests to avoid calling real AWS.
- `RunTesseract` is a variable; replace it in tests with a fake function that returns deterministic text.
- Test `deriveOutputKey`, `isImageFile`, and `ProcessImage` behavior with controlled mocks.

## SQS message format
When OCR succeeds the code sends a JSON message like:
```json
{
  "source_bucket": "<bucket>",
  "source_key": "<key>",
  "output_bucket": "ocr-output",
  "output_key": "<key>.txt",
  "text_length": 123
}
```

## Troubleshooting
- "tesseract: command not found": ensure the binary is installed and on PATH in the runtime environment.
- Empty output: check image quality and Tesseract language/data availability.
- `GetQueueUrl` fails at startup: ensure the queue `ocr-results` exists and the Lambda role or local creds can call `sqs:GetQueueUrl`.

## Quick checklist for a working dev environment
- [ ] Install Go (1.22+) and build the `lambda` binary.
- [ ] Install Tesseract on the machine or container.
- [ ] Start LocalStack / MinIO if testing locally.
- [ ] Set `AWS_ENDPOINT_URL` and `AWS_DEFAULT_REGION` for local testing.
- [ ] Create S3 buckets and SQS queue in your test endpoint.
- [ ] Run tests with mocks for fast unit tests.

---
If you'd like, I can also:
- Add a `Dockerfile` that builds a container with the Go binary and Tesseract installed for local testing.
- Add unit test examples that mock `S3Client`/`SQSClient` and `RunTesseract`.

Which of those would you like next?
