import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';

const LS = process.env.LOCALSTACK_URL || 'http://localhost:4566';

// ─── S3 ───

export async function s3Put(bucket: string, key: string, filePath: string): Promise<void> {
  const data = fs.readFileSync(filePath);
  const r = await fetch(`${LS}/${bucket}/${encodeURIComponent(key)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: data,
  });
  if (!r.ok) throw new Error(`s3Put ${r.status}: ${await r.text()}`);
}

export async function s3Get(bucket: string, key: string): Promise<string | null> {
  try {
    const r = await fetch(`${LS}/${bucket}/${encodeURIComponent(key)}`);
    if (!r.ok) return null;
    return await r.text();
  } catch { return null; }
}

export async function s3Exists(bucket: string, key: string): Promise<boolean> {
  try {
    const r = await fetch(`${LS}/${bucket}/${encodeURIComponent(key)}`, { method: 'HEAD' });
    return r.ok;
  } catch { return false; }
}

// ─── SQS ───

async function sqsAction(params: Record<string, string>): Promise<string> {
  const body = new URLSearchParams({ ...params, Version: '2012-11-05' }).toString();
  const r = await fetch(LS, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  return r.text();
}

export async function sqsPurge(queue: string): Promise<void> {
  try {
    const xml = await sqsAction({ Action: 'GetQueueUrl', QueueName: queue });
    const m = xml.match(/<QueueUrl>([^<]+)<\/QueueUrl>/);
    if (m) await sqsAction({ Action: 'PurgeQueue', QueueUrl: m[1] });
  } catch { /* ignore */ }
}

export async function sqsReceive(queue: string, max = 10): Promise<any[]> {
  try {
    const xml1 = await sqsAction({ Action: 'GetQueueUrl', QueueName: queue });
    const m1 = xml1.match(/<QueueUrl>([^<]+)<\/QueueUrl>/);
    if (!m1) return [];
    const xml2 = await sqsAction({
      Action: 'ReceiveMessage', QueueUrl: m1[1],
      MaxNumberOfMessages: String(max), WaitTimeSeconds: '5',
    });
    const msgs: any[] = [];
    const re = /<Message>[\s\S]*?<Body>([^<]+)<\/Body>[\s\S]*?<\/Message>/g;
    let match;
    while ((match = re.exec(xml2)) !== null) {
      msgs.push({ Body: match[1].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"') });
    }
    return msgs;
  } catch { return []; }
}

// ─── Polling ───

export async function waitForS3(bucket: string, key: string, timeoutMs = 60000): Promise<string | null> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const txt = await s3Get(bucket, key);
    if (txt !== null) return txt;
    await new Promise(r => setTimeout(r, 2000));
  }
  return null;
}

// ─── Test Image Generation (ImageMagick) ───

function imCmd(): string {
  try { execSync('which magick', { stdio: 'ignore' }); return 'magick'; }
  catch {
    try { execSync('which convert', { stdio: 'ignore' }); return 'convert'; }
    catch { throw new Error('ImageMagick not found'); }
  }
}

export function makeTextImage(text: string, out: string): void {
  const dir = path.dirname(out);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  execSync(`${imCmd()} -size 600x200 xc:white -font DejaVu-Sans -pointsize 48 -gravity center -annotate 0 "${text}" "${out}"`, { timeout: 15000 });
}

export function makeBlankImage(out: string): void {
  const dir = path.dirname(out);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  execSync(`${imCmd()} -size 400x200 xc:white "${out}"`, { timeout: 15000 });
}
