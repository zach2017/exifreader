#!/bin/bash
set -e

echo "=== Initializing LocalStack resources ==="

# Create S3 Buckets
awslocal s3 mb s3://uploads
awslocal s3 mb s3://extracted-text
awslocal s3 mb s3://tmp-files
awslocal s3 mb s3://tmp-extracted-text

echo "S3 buckets created."

# Create SQS Queues
awslocal sqs create-queue --queue-name file-processing
awslocal sqs create-queue --queue-name ocr-processing
awslocal sqs create-queue --queue-name ocr-complete

echo "SQS queues created."
echo "=== LocalStack initialization complete ==="
