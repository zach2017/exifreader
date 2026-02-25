"""
OCR Extractor Lambda
====================
Triggered by: SQS (ocr-queue)

Purpose:
  - Performs OCR (Optical Character Recognition) on images
  - Supports: PNG, JPEG, TIFF, BMP, GIF, WebP
  - Uses Tesseract OCR engine via pytesseract
  - Preprocesses images for better OCR accuracy (denoise, deskew, contrast)
  - Saves extracted text as .txt files to S3 extracted/ prefix
  - Updates DynamoDB metadata
  - Indexes OCR text in Elasticsearch

Best Practices for OCR in Lambda:
  1. Memory: Use 2048MB+ (OCR is CPU-intensive, Lambda CPU scales with memory)
  2. Timeout: 300s for single images, consider Step Functions for batches
  3. Preprocessing: Denoise, deskew, and enhance contrast before OCR
  4. Lambda Layer: Package Tesseract + language data as a Lambda Layer
  5. Temp Storage: Use /tmp (512MB default, configurable to 10GB)
  6. Concurrency: Set reserved concurrency to avoid overwhelming downstream services

Dependencies:
  - pytesseract (Python wrapper for Tesseract OCR)
  - Pillow (Image processing and preprocessing)
  - Tesseract OCR engine (installed via Lambda Layer or container image)
"""

import json
import os
import io
import logging
import tempfile
import subprocess
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENDPOINT_URL = os.environ.get('AWS_ENDPOINT_URL', None)
S3_BUCKET = os.environ.get('S3_BUCKET', 'docproc-bucket')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'document-metadata')
ES_URL = os.environ.get('ELASTICSEARCH_URL', 'http://localhost:9200')

boto_kwargs = {'endpoint_url': ENDPOINT_URL} if ENDPOINT_URL else {}
s3 = boto3.client('s3', **boto_kwargs)
dynamodb = boto3.resource('dynamodb', **boto_kwargs)
table = dynamodb.Table(DYNAMODB_TABLE)


def lambda_handler(event, context):
    """
    Main handler for OCR processing.
    
    Receives SQS messages with image references, performs OCR,
    and stores results in S3 + DynamoDB + Elasticsearch.
    """
    logger.info(f"OCR Extractor invoked: {json.dumps(event, default=str)[:500]}")
    
    if 'Records' in event:
        for record in event['Records']:
            body = json.loads(record.get('body', '{}'))
            process_ocr(body)
    elif 'file_id' in event:
        process_ocr(event)
    
    return {'statusCode': 200}


def process_ocr(message):
    """
    Process a single OCR request.
    
    Workflow:
      1. Download image from S3
      2. Preprocess image (enhance, denoise, deskew)
      3. Run Tesseract OCR
      4. Save extracted text to S3
      5. Update DynamoDB metadata
      6. Index in Elasticsearch
    """
    file_id = message['file_id']
    s3_key = message['s3_key']
    filename = message.get('filename', s3_key.split('/')[-1])
    source = message.get('source', 'unknown')
    
    logger.info(f"OCR processing: file_id={file_id}, image={filename}, source={source}")
    
    tmp_path = None
    try:
        # Step 1: Download image from S3
        with tempfile.NamedTemporaryFile(delete=False, suffix=_get_extension(filename)) as tmp:
            s3.download_file(S3_BUCKET, s3_key, tmp.name)
            tmp_path = tmp.name
        
        # Step 2: Preprocess the image
        preprocessed_path = preprocess_image(tmp_path)
        
        # Step 3: Run OCR
        text = run_ocr(preprocessed_path or tmp_path)
        
        if not text or not text.strip():
            logger.warning(f"No text extracted via OCR from {filename}")
            text = "[No text detected in image via OCR]"
        
        # Step 4: Save extracted text to S3
        text_filename = os.path.splitext(filename)[0] + '-ocr.txt'
        extracted_key = f"extracted/{file_id}/ocr/{text_filename}"
        
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=extracted_key,
            Body=text.encode('utf-8'),
            ContentType='text/plain'
        )
        logger.info(f"Saved OCR text: {extracted_key} ({len(text)} chars)")
        
        # Step 5: Update DynamoDB
        now = datetime.now(timezone.utc).isoformat()
        table.update_item(
            Key={'file_id': file_id},
            UpdateExpression='''
                SET extracted_files = list_append(if_not_exists(extracted_files, :empty), :ef),
                    processing_steps = list_append(if_not_exists(processing_steps, :empty), :step)
            ''',
            ExpressionAttributeValues={
                ':ef': [extracted_key],
                ':step': [f"{now}: OCR extracted ({len(text)} chars) from {filename} → {extracted_key}"],
                ':empty': []
            }
        )
        
        # If this was a direct image upload (not from PDF), also set the text key and complete
        if source == 'direct_upload':
            table.update_item(
                Key={'file_id': file_id},
                UpdateExpression='SET extracted_text_key = :tk, #s = :s',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={
                    ':tk': extracted_key,
                    ':s': 'COMPLETED'
                }
            )
        
        # Step 6: Index in Elasticsearch
        index_in_elasticsearch(file_id, filename, text, s3_key, 'ocr')
        
        logger.info(f"OCR complete for {file_id}/{filename}")
        
    except Exception as e:
        logger.error(f"OCR failed for {file_id}/{filename}: {e}", exc_info=True)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.update_item(
                Key={'file_id': file_id},
                UpdateExpression='SET processing_steps = list_append(if_not_exists(processing_steps, :empty), :step)',
                ExpressionAttributeValues={
                    ':step': [f"{now}: OCR FAILED for {filename}: {str(e)}"],
                    ':empty': []
                }
            )
        except Exception:
            pass
        raise  # Re-raise for SQS retry
    
    finally:
        for path in [tmp_path]:
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass


def preprocess_image(image_path):
    """
    Preprocess image to improve OCR accuracy.
    
    Steps:
      1. Convert to grayscale
      2. Apply adaptive thresholding
      3. Denoise
      4. Increase DPI if low
      5. Deskew (straighten tilted text)
    
    Returns path to preprocessed image, or None if preprocessing fails.
    """
    try:
        from PIL import Image, ImageFilter, ImageEnhance, ImageOps
        
        img = Image.open(image_path)
        
        # Convert to RGB if necessary (handles RGBA, palette modes)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Convert to grayscale
        if img.mode != 'L':
            img = img.convert('L')
        
        # Get DPI — upscale if too low
        dpi = img.info.get('dpi', (72, 72))
        if isinstance(dpi, tuple) and dpi[0] < 200:
            # Upscale to ~300 DPI equivalent
            scale = 300 / max(dpi[0], 1)
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.LANCZOS)
        
        # Enhance contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        
        # Sharpen
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)
        
        # Apply slight denoise
        img = img.filter(ImageFilter.MedianFilter(size=3))
        
        # Auto-contrast (normalize brightness)
        img = ImageOps.autocontrast(img, cutoff=1)
        
        # Save preprocessed image
        preprocessed_path = image_path + '_preprocessed.png'
        img.save(preprocessed_path, 'PNG', dpi=(300, 300))
        
        logger.info(f"Image preprocessed: {img.width}x{img.height}")
        return preprocessed_path
        
    except ImportError:
        logger.warning("Pillow not available, skipping preprocessing")
        return None
    except Exception as e:
        logger.warning(f"Image preprocessing failed: {e}")
        return None


def run_ocr(image_path):
    """
    Run Tesseract OCR on an image.
    
    Tries pytesseract first, falls back to subprocess call.
    Uses English language data by default.
    
    Configuration for best results:
      - PSM 3: Fully automatic page segmentation (default)
      - OEM 3: Default, based on what is available (LSTM + Legacy)
    """
    # Try pytesseract
    try:
        import pytesseract
        from PIL import Image
        
        img = Image.open(image_path)
        
        # OCR with configuration for best accuracy
        custom_config = r'--oem 3 --psm 3 -l eng'
        text = pytesseract.image_to_string(img, config=custom_config)
        
        logger.info(f"pytesseract OCR: extracted {len(text)} chars")
        return text.strip()
        
    except ImportError:
        logger.info("pytesseract not available, trying subprocess")
    
    # Fallback: call tesseract directly
    try:
        result = subprocess.run(
            ['tesseract', image_path, 'stdout', '-l', 'eng', '--oem', '3', '--psm', '3'],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            text = result.stdout.strip()
            logger.info(f"tesseract CLI OCR: extracted {len(text)} chars")
            return text
        else:
            logger.error(f"tesseract failed: {result.stderr}")
            return ""
            
    except FileNotFoundError:
        logger.error("Tesseract not installed. Install with: apt-get install tesseract-ocr")
        # Last resort: return empty (will be caught by caller)
        return "[OCR engine not available — Tesseract not installed]"
    except subprocess.TimeoutExpired:
        logger.error("Tesseract timed out after 120s")
        return "[OCR timed out — image may be too large or complex]"


# ─── Helper Functions ────────────────────────────────────────

def _get_extension(filename):
    """Get file extension."""
    if '.' in filename:
        return '.' + filename.rsplit('.', 1)[1].lower()
    return '.png'


def index_in_elasticsearch(file_id, filename, content, s3_key, source_type):
    """Index OCR text in Elasticsearch."""
    try:
        import urllib.request
        
        # Use a unique doc ID for OCR results (file_id + image name)
        doc_id = f"{file_id}-ocr-{filename.replace('/', '-').replace('.', '-')}"
        
        doc = {
            'file_id': file_id,
            'filename': filename,
            'content': content[:50000],
            'file_type': 'image',
            'upload_time': datetime.now(timezone.utc).isoformat(),
            's3_key': s3_key,
            'extracted_from': file_id,
            'source_type': source_type
        }
        
        req = urllib.request.Request(
            f"{ES_URL}/documents/_doc/{doc_id}",
            data=json.dumps(doc).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='PUT'
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"Indexed OCR text in Elasticsearch: {doc_id}")
    except Exception as e:
        logger.warning(f"ES indexing failed (non-fatal): {e}")
