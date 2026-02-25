"""
File Router Lambda
==================
Triggered by: SQS (file-router-queue) on S3 upload events
              Step Functions (for batch OCR send, text extract send, metadata update)

Purpose:
  - Detects file type from uploaded S3 object
  - Routes to appropriate processing pipeline:
    * PDF → Step Function (multi-step: image extraction + OCR + text extract)
    * DOCX/DOC → SQS text-extract-queue
    * Images (PNG, JPG, TIFF, BMP) → SQS ocr-queue
    * Plain text → Direct store, mark as completed
    * Other formats → SQS text-extract-queue (attempt extraction)
  - Creates initial DynamoDB metadata record
  - Supports Step Function callback actions (send_ocr_batch, send_text_extract, update_metadata)
"""

import json
import os
import uuid
import logging
import mimetypes
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3

# ─── Configuration ──────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENDPOINT_URL = os.environ.get('AWS_ENDPOINT_URL', None)
S3_BUCKET = os.environ.get('S3_BUCKET', 'docproc-bucket')
TEXT_EXTRACT_QUEUE_URL = os.environ.get('TEXT_EXTRACT_QUEUE_URL')
OCR_QUEUE_URL = os.environ.get('OCR_QUEUE_URL')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'document-metadata')
STEP_FUNCTION_ARN = os.environ.get('STEP_FUNCTION_ARN')
ES_URL = os.environ.get('ELASTICSEARCH_URL', 'http://localhost:9200')

# ─── AWS Clients (reused across invocations for connection pooling) ──
boto_kwargs = {'endpoint_url': ENDPOINT_URL} if ENDPOINT_URL else {}
s3 = boto3.client('s3', **boto_kwargs)
sqs = boto3.client('sqs', **boto_kwargs)
dynamodb = boto3.resource('dynamodb', **boto_kwargs)
sfn = boto3.client('stepfunctions', **boto_kwargs)
table = dynamodb.Table(DYNAMODB_TABLE)

# ─── File Type Classification ───────────────────────────────
MIME_CATEGORIES = {
    'pdf': ['application/pdf'],
    'word': [
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ],
    'image': [
        'image/png', 'image/jpeg', 'image/jpg', 'image/tiff',
        'image/bmp', 'image/gif', 'image/webp'
    ],
    'text': [
        'text/plain', 'text/csv', 'text/html', 'text/xml',
        'application/json', 'text/markdown'
    ],
    'spreadsheet': [
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    ],
    'presentation': [
        'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ]
}

def classify_file(filename, content_type=None):
    """Classify file into processing category based on MIME type and extension."""
    if not content_type:
        content_type, _ = mimetypes.guess_type(filename)
    
    if not content_type:
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        ext_map = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'tiff': 'image/tiff', 'tif': 'image/tiff', 'bmp': 'image/bmp',
            'gif': 'image/gif', 'webp': 'image/webp',
            'txt': 'text/plain', 'csv': 'text/csv', 'md': 'text/markdown',
            'json': 'application/json', 'xml': 'text/xml', 'html': 'text/html',
        }
        content_type = ext_map.get(ext, 'application/octet-stream')
    
    for category, mime_types in MIME_CATEGORIES.items():
        if content_type in mime_types:
            return category, content_type
    
    return 'other', content_type


def lambda_handler(event, context):
    """
    Main Lambda handler — dispatches based on event source.
    
    Handles:
      1. SQS events (from S3 notification via file-router-queue)
      2. Step Function invocations (action-based: send_ocr_batch, send_text_extract, update_metadata)
    """
    logger.info(f"Event received: {json.dumps(event, default=str)[:500]}")
    
    # ── Step Function action dispatch ──
    if 'action' in event:
        return handle_step_function_action(event)
    
    # ── SQS event from S3 notification ──
    if 'Records' in event:
        for record in event['Records']:
            try:
                body = json.loads(record.get('body', '{}'))
                
                # S3 event nested in SQS message
                if 'Records' in body:
                    for s3_record in body['Records']:
                        process_s3_event(s3_record)
                elif 's3' in body:
                    process_s3_event(body)
                else:
                    logger.warning(f"Unknown SQS message format: {json.dumps(body)[:200]}")
                    
            except Exception as e:
                logger.error(f"Error processing record: {e}", exc_info=True)
                raise  # Re-raise to trigger SQS retry / DLQ
    
    return {'statusCode': 200, 'body': 'OK'}


def process_s3_event(s3_record):
    """Process a single S3 event — classify file and route to correct pipeline."""
    bucket = s3_record['s3']['bucket']['name']
    key = unquote_plus(s3_record['s3']['object']['key'])
    size = s3_record['s3']['object'].get('size', 0)
    
    # Skip if not in uploads/ prefix
    if not key.startswith('uploads/'):
        logger.info(f"Skipping non-upload key: {key}")
        return
    
    # Extract filename from key: uploads/{file_id}/{filename}
    parts = key.split('/')
    if len(parts) < 3:
        logger.error(f"Unexpected key format: {key}")
        return
    
    file_id = parts[1]
    filename = '/'.join(parts[2:])
    
    logger.info(f"Processing upload: file_id={file_id}, filename={filename}")
    
    # Classify the file
    category, content_type = classify_file(filename)
    logger.info(f"Classified as: category={category}, mime={content_type}")
    
    # Create DynamoDB metadata record
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        'file_id': file_id,
        'original_key': key,
        'filename': filename,
        'file_type': content_type,
        'file_category': category,
        'file_size': size,
        'upload_time': now,
        'status': 'PROCESSING',
        'extracted_files': [],
        'extracted_text_key': '',
        'processing_steps': [f"{now}: File uploaded, classified as {category}"]
    }
    table.put_item(Item=metadata)
    logger.info(f"DynamoDB record created for {file_id}")
    
    # Route based on category
    if category == 'pdf':
        route_pdf(file_id, key)
    elif category == 'word' or category == 'spreadsheet' or category == 'presentation':
        route_to_text_extract(file_id, key, filename, content_type)
    elif category == 'image':
        route_to_ocr(file_id, key, filename)
    elif category == 'text':
        route_plain_text(file_id, key, filename)
    else:
        route_to_text_extract(file_id, key, filename, content_type)


def route_pdf(file_id, s3_key):
    """Start Step Function execution for PDF processing pipeline."""
    logger.info(f"Starting Step Function for PDF: {file_id}")
    
    try:
        sfn.start_execution(
            stateMachineArn=STEP_FUNCTION_ARN,
            name=f"pdf-{file_id}-{int(datetime.now(timezone.utc).timestamp())}",
            input=json.dumps({
                'file_id': file_id,
                's3_key': s3_key
            })
        )
        update_processing_step(file_id, "Step Function started for PDF processing")
    except Exception as e:
        logger.error(f"Failed to start Step Function: {e}")
        # Fallback: send directly to text extract queue
        route_to_text_extract(file_id, s3_key, '', 'application/pdf')


def route_to_text_extract(file_id, s3_key, filename, content_type):
    """Send message to text-extract-queue for document text extraction."""
    logger.info(f"Routing to text extraction: {file_id}")
    
    sqs.send_message(
        QueueUrl=TEXT_EXTRACT_QUEUE_URL,
        MessageBody=json.dumps({
            'file_id': file_id,
            's3_key': s3_key,
            'filename': filename,
            'content_type': content_type,
            'action': 'extract_text'
        })
    )
    update_processing_step(file_id, f"Sent to text extraction queue ({content_type})")


def route_to_ocr(file_id, s3_key, filename):
    """Send message to ocr-queue for image OCR processing."""
    logger.info(f"Routing to OCR: {file_id}")
    
    sqs.send_message(
        QueueUrl=OCR_QUEUE_URL,
        MessageBody=json.dumps({
            'file_id': file_id,
            's3_key': s3_key,
            'filename': filename,
            'action': 'ocr_extract',
            'source': 'direct_upload'
        })
    )
    update_processing_step(file_id, "Sent to OCR queue (image upload)")


def route_plain_text(file_id, s3_key, filename):
    """
    Plain text files don't need extraction — copy to extracted/ and mark complete.
    """
    logger.info(f"Processing plain text: {file_id}")
    
    try:
        # Read the text content
        response = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        text_content = response['Body'].read().decode('utf-8', errors='replace')
        
        # Save a copy to extracted/
        extracted_key = f"extracted/{file_id}/{filename}"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=extracted_key,
            Body=text_content.encode('utf-8'),
            ContentType='text/plain'
        )
        
        # Update DynamoDB
        table.update_item(
            Key={'file_id': file_id},
            UpdateExpression='SET #s = :s, extracted_text_key = :tk, extracted_files = list_append(extracted_files, :ef)',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':s': 'COMPLETED',
                ':tk': extracted_key,
                ':ef': [extracted_key]
            }
        )
        
        # Index in Elasticsearch
        index_in_elasticsearch(file_id, filename, text_content, s3_key, 'text')
        
        update_processing_step(file_id, "Plain text stored and indexed directly")
        logger.info(f"Plain text processing complete: {file_id}")
        
    except Exception as e:
        logger.error(f"Error processing plain text {file_id}: {e}")
        update_status(file_id, 'ERROR')


def handle_step_function_action(event):
    """
    Handle actions called from Step Functions.
    
    Actions:
      - send_ocr_batch: Send OCR messages for each extracted PDF image
      - send_text_extract: Send text extraction message for PDF text layer
      - update_metadata: Update DynamoDB status
    """
    action = event['action']
    file_id = event['file_id']
    
    logger.info(f"Step Function action: {action} for {file_id}")
    
    if action == 'send_ocr_batch':
        image_keys = event.get('image_keys', [])
        for img_key in image_keys:
            sqs.send_message(
                QueueUrl=OCR_QUEUE_URL,
                MessageBody=json.dumps({
                    'file_id': file_id,
                    's3_key': img_key,
                    'filename': img_key.split('/')[-1],
                    'action': 'ocr_extract',
                    'source': 'pdf_extraction'
                })
            )
        update_processing_step(file_id, f"Sent {len(image_keys)} images to OCR queue")
        return {'statusCode': 200, 'images_queued': len(image_keys)}
    
    elif action == 'send_text_extract':
        s3_key = event['s3_key']
        sqs.send_message(
            QueueUrl=TEXT_EXTRACT_QUEUE_URL,
            MessageBody=json.dumps({
                'file_id': file_id,
                's3_key': s3_key,
                'content_type': 'application/pdf',
                'action': 'extract_text'
            })
        )
        update_processing_step(file_id, "Sent PDF to text extraction queue")
        return {'statusCode': 200, 'text_extract_queued': True}
    
    elif action == 'update_metadata':
        status = event.get('status', 'PROCESSING')
        update_status(file_id, status)
        return {'statusCode': 200, 'status': status}
    
    else:
        logger.warning(f"Unknown action: {action}")
        return {'statusCode': 400, 'error': f'Unknown action: {action}'}


# ─── Helper Functions ───────────────────────────────────────

def update_processing_step(file_id, step_description):
    """Append a processing step to the DynamoDB record."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        table.update_item(
            Key={'file_id': file_id},
            UpdateExpression='SET processing_steps = list_append(processing_steps, :step)',
            ExpressionAttributeValues={
                ':step': [f"{now}: {step_description}"]
            }
        )
    except Exception as e:
        logger.warning(f"Failed to update processing step: {e}")


def update_status(file_id, status):
    """Update the status field in DynamoDB."""
    try:
        table.update_item(
            Key={'file_id': file_id},
            UpdateExpression='SET #s = :s',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': status}
        )
    except Exception as e:
        logger.warning(f"Failed to update status: {e}")


def index_in_elasticsearch(file_id, filename, content, s3_key, source_type):
    """Index extracted text in Elasticsearch for full-text search."""
    try:
        import urllib.request
        doc = {
            'file_id': file_id,
            'filename': filename,
            'content': content[:50000],  # Limit to 50K chars for ES
            'file_type': source_type,
            'upload_time': datetime.now(timezone.utc).isoformat(),
            's3_key': s3_key,
            'source_type': source_type
        }
        
        req = urllib.request.Request(
            f"{ES_URL}/documents/_doc/{file_id}",
            data=json.dumps(doc).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='PUT'
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"Indexed in Elasticsearch: {file_id}")
    except Exception as e:
        logger.warning(f"Elasticsearch indexing failed (non-fatal): {e}")
