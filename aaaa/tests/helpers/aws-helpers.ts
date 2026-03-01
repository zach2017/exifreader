import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';
import * as crypto from 'crypto';

const LOCALSTACK_URL = process.env.LOCALSTACK_URL || 'http://localhost:4566';
const REGION = process.env.AWS_DEFAULT_REGION || 'us-east-1';
const ACCESS_KEY = process.env.AWS_ACCESS_KEY_ID || 'test';
const SECRET_KEY = process.env.AWS_SECRET_ACCESS_KEY || 'test';

// ─── AWS Signature V4 (minimal implementation for LocalStack) ───

function hmacSHA256(key: Buffer | string, data: string): Buffer {
  return crypto.createHmac('sha256', key).update(data, 'utf8').digest();
}

function sha256(data: string | Buffer): string {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function getSignatureKey(key: string, dateStamp: string, region: string, service: string): Buffer {
  const kDate = hmacSHA256(Buffer.from('AWS4' + key, 'utf8'), dateStamp);
  const kRegion = hmacSHA256(kDate, region);
  const kService = hmacSHA256(kRegion, service);
  const kSigning = hmacSHA256(kService, 'aws4_request');
  return kSigning;
}

function signRequest(
  method: string,
  url: string,
  headers: Record<string, string>,
  body: string | Buffer,
  service: string
): Record<string, string> {
  const parsedUrl = new URL(url);
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, '').slice(0, 15) + 'Z';
  const dateStamp = amzDate.slice(0, 8);

  const payloadHash = sha256(body);
  headers['x-amz-date'] = amzDate;
  headers['x-amz-content-sha256'] = payloadHash;
  headers['host'] = parsedUrl.host;

  const signedHeaderKeys = Object.keys(headers)
    .map(k => k.toLowerCase())
    .sort();
  const signedHeaders = signedHeaderKeys.join(';');

  const canonicalHeaders = signedHeaderKeys
    .map(k => `${k}:${headers[Object.keys(headers).find(h => h.toLowerCase() === k)!].trim()}`)
    .join('\n') + '\n';

  const canonicalQueryString = parsedUrl.search ? parsedUrl.search.slice(1) : '';
  const canonicalRequest = [
    method,
    parsedUrl.pathname,
    canonicalQueryString,
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join('\n');

  const credentialScope = `${dateStamp}/${REGION}/${service}/aws4_request`;
  const stringToSign = [
    'AWS4-HMAC-SHA256',
    amzDate,
    credentialScope,
    sha256(canonicalRequest),
  ].join('\n');

  const signingKey = getSignatureKey(SECRET_KEY, dateStamp, REGION, service);
  const signature = hmacSHA256(signingKey, stringToSign).toString('hex');

  headers['Authorization'] =
    `AWS4-HMAC-SHA256 Credential=${ACCESS_KEY}/${credentialScope}, ` +
    `SignedHeaders=${signedHeaders}, Signature=${signature}`;

  return headers;
}

// ─── S3 Helpers (pure HTTP) ───

export async function s3PutObject(bucket: string, key: string, filePath: string): Promise<void> {
  const fileData = fs.readFileSync(filePath);
  const url = `${LOCALSTACK_URL}/${bucket}/${encodeURIComponent(key)}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/octet-stream',
  };
  signRequest('PUT', url, headers, fileData, 's3');

  const resp = await fetch(url, { method: 'PUT', headers, body: fileData });
  if (!resp.ok) {
    throw new Error(`s3PutObject failed: ${resp.status} ${await resp.text()}`);
  }
}

export async function s3GetObject(bucket: string, key: string): Promise<string | null> {
  const url = `${LOCALSTACK_URL}/${bucket}/${encodeURIComponent(key)}`;
  const headers: Record<string, string> = {};
  signRequest('GET', url, headers, '', 's3');

  try {
    const resp = await fetch(url, { method: 'GET', headers });
    if (resp.status === 404 || resp.status === 403) return null;
    if (!resp.ok) return null;
    return await resp.text();
  } catch {
    return null;
  }
}

export async function s3ObjectExists(bucket: string, key: string): Promise<boolean> {
  const url = `${LOCALSTACK_URL}/${bucket}/${encodeURIComponent(key)}`;
  const headers: Record<string, string> = {};
  signRequest('HEAD', url, headers, '', 's3');

  try {
    const resp = await fetch(url, { method: 'HEAD', headers });
    return resp.ok;
  } catch {
    return false;
  }
}

export async function s3ListObjects(bucket: string): Promise<string[]> {
  const url = `${LOCALSTACK_URL}/${bucket}?list-type=2`;
  const headers: Record<string, string> = {};
  signRequest('GET', url, headers, '', 's3');

  try {
    const resp = await fetch(url, { method: 'GET', headers });
    if (!resp.ok) return [];
    const xml = await resp.text();
    const keys: string[] = [];
    const regex = /<Key>([^<]+)<\/Key>/g;
    let match;
    while ((match = regex.exec(xml)) !== null) {
      keys.push(match[1]);
    }
    return keys;
  } catch {
    return [];
  }
}

// ─── SQS Helpers (pure HTTP) ───

async function sqsRequest(params: Record<string, string>): Promise<string> {
  const url = `${LOCALSTACK_URL}`;
  const bodyParams = new URLSearchParams(params);
  const bodyStr = bodyParams.toString();

  const headers: Record<string, string> = {
    'Content-Type': 'application/x-www-form-urlencoded',
  };
  signRequest('POST', url, headers, bodyStr, 'sqs');

  const resp = await fetch(url, { method: 'POST', headers, body: bodyStr });
  return await resp.text();
}

async function sqsGetQueueUrl(queueName: string): Promise<string> {
  const xml = await sqsRequest({
    Action: 'GetQueueUrl',
    QueueName: queueName,
    Version: '2012-11-05',
  });
  const match = xml.match(/<QueueUrl>([^<]+)<\/QueueUrl>/);
  if (!match) throw new Error(`Queue ${queueName} not found: ${xml}`);
  return match[1];
}

export async function sqsReceiveMessages(queueName: string, maxMessages = 10): Promise<any[]> {
  try {
    const queueUrl = await sqsGetQueueUrl(queueName);
    const xml = await sqsRequest({
      Action: 'ReceiveMessage',
      QueueUrl: queueUrl,
      MaxNumberOfMessages: String(maxMessages),
      WaitTimeSeconds: '5',
      Version: '2012-11-05',
    });

    const messages: any[] = [];
    const msgRegex = /<Message>([\s\S]*?)<\/Message>/g;
    let msgMatch;
    while ((msgMatch = msgRegex.exec(xml)) !== null) {
      const bodyMatch = msgMatch[1].match(/<Body>([^<]+)<\/Body>/);
      const idMatch = msgMatch[1].match(/<MessageId>([^<]+)<\/MessageId>/);
      const receiptMatch = msgMatch[1].match(/<ReceiptHandle>([^<]+)<\/ReceiptHandle>/);
      if (bodyMatch) {
        messages.push({
          MessageId: idMatch?.[1] || '',
          Body: bodyMatch[1],
          ReceiptHandle: receiptMatch?.[1] || '',
        });
      }
    }
    return messages;
  } catch {
    return [];
  }
}

export async function sqsPurge(queueName: string): Promise<void> {
  try {
    const queueUrl = await sqsGetQueueUrl(queueName);
    await sqsRequest({
      Action: 'PurgeQueue',
      QueueUrl: queueUrl,
      Version: '2012-11-05',
    });
  } catch {
    // ignore — queue may not exist yet
  }
}

// ─── Polling Helper ───

export async function waitForS3Object(
  bucket: string,
  key: string,
  timeoutMs = 60_000
): Promise<string | null> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const content = await s3GetObject(bucket, key);
    if (content !== null) return content;
    await new Promise(r => setTimeout(r, 2000));
  }
  return null;
}

// ─── Image Generation (ImageMagick) ───

export function generateTestImage(text: string, outputPath: string): void {
  const dir = path.dirname(outputPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  const cmd = getImageMagickCmd();
  execSync(
    `${cmd} -size 600x200 xc:white -font DejaVu-Sans -pointsize 48 -gravity center -annotate 0 "${text}" "${outputPath}"`,
    { timeout: 15_000 }
  );
}

export function generateBlankImage(outputPath: string): void {
  const dir = path.dirname(outputPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  const cmd = getImageMagickCmd();
  execSync(`${cmd} -size 400x200 xc:white "${outputPath}"`, { timeout: 15_000 });
}

function getImageMagickCmd(): string {
  try {
    execSync('which magick', { stdio: 'ignore' });
    return 'magick';
  } catch {
    try {
      execSync('which convert', { stdio: 'ignore' });
      return 'convert';
    } catch {
      throw new Error('ImageMagick not found. Install imagemagick package.');
    }
  }
}
