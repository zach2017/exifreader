import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

const LOCALSTACK_URL = process.env.LOCALSTACK_URL || 'http://localhost:4566';
const REGION = process.env.AWS_DEFAULT_REGION || 'us-east-1';

const awsEnv = {
  ...process.env,
  AWS_ACCESS_KEY_ID: 'test',
  AWS_SECRET_ACCESS_KEY: 'test',
  AWS_DEFAULT_REGION: REGION,
};

function aws(cmd: string): string {
  const full = `aws --endpoint-url=${LOCALSTACK_URL} --region=${REGION} ${cmd}`;
  return execSync(full, { env: awsEnv, encoding: 'utf-8', timeout: 30_000 }).trim();
}

export function s3ListObjects(bucket: string): string[] {
  try {
    const result = aws(`s3api list-objects-v2 --bucket ${bucket} --query "Contents[].Key" --output json`);
    return JSON.parse(result || '[]') || [];
  } catch {
    return [];
  }
}

export function s3GetObject(bucket: string, key: string): string | null {
  try {
    const tmpFile = `/tmp/s3-get-${Date.now()}.txt`;
    aws(`s3 cp s3://${bucket}/${key} ${tmpFile}`);
    const content = fs.readFileSync(tmpFile, 'utf-8');
    fs.unlinkSync(tmpFile);
    return content;
  } catch {
    return null;
  }
}

export function s3PutObject(bucket: string, key: string, filePath: string): void {
  aws(`s3 cp ${filePath} s3://${bucket}/${key}`);
}

export function s3ObjectExists(bucket: string, key: string): boolean {
  try {
    aws(`s3api head-object --bucket ${bucket} --key ${key}`);
    return true;
  } catch {
    return false;
  }
}

export function sqsReceiveMessages(queueName: string, maxMessages = 10): any[] {
  try {
    const urlResult = aws(`sqs get-queue-url --queue-name ${queueName} --output json`);
    const queueUrl = JSON.parse(urlResult).QueueUrl;
    const result = aws(
      `sqs receive-message --queue-url ${queueUrl} --max-number-of-messages ${maxMessages} --wait-time-seconds 5 --output json`
    );
    const parsed = JSON.parse(result || '{}');
    return parsed.Messages || [];
  } catch {
    return [];
  }
}

export function sqsPurge(queueName: string): void {
  try {
    const urlResult = aws(`sqs get-queue-url --queue-name ${queueName} --output json`);
    const queueUrl = JSON.parse(urlResult).QueueUrl;
    aws(`sqs purge-queue --queue-url ${queueUrl}`);
  } catch {
    // ignore
  }
}

export function waitForS3Object(bucket: string, key: string, timeoutMs = 60_000): string | null {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const content = s3GetObject(bucket, key);
    if (content !== null) return content;
    execSync('sleep 2');
  }
  return null;
}

export function generateTestImage(text: string, outputPath: string): void {
  // Use ImageMagick to create a test image with text
  execSync(
    `convert -size 400x200 xc:white -font DejaVu-Sans -pointsize 36 -gravity center -annotate 0 "${text}" ${outputPath}`,
    { timeout: 10_000 }
  );
}

export function generateBlankImage(outputPath: string): void {
  execSync(`convert -size 400x200 xc:white ${outputPath}`, { timeout: 10_000 });
}
