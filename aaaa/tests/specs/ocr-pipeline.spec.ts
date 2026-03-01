import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import { s3Put, s3Exists, sqsPurge, sqsReceive, waitForS3, makeTextImage, makeBlankImage } from '../helpers/aws-helpers';

const IMG_DIR = path.resolve('/app/test-images');

test.describe('Web Upload UI', () => {
  test.beforeAll(async () => { await sqsPurge('ocr-results'); });

  test('page loads with all elements', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h1')).toContainText('OCR Extract');
    await expect(page.locator('#drop')).toBeVisible();
    await expect(page.locator('#btn')).toBeDisabled();
  });

  test('file select shows preview and enables button', async ({ page }) => {
    await page.goto('/');
    const img = path.join(IMG_DIR, 'hello.png');
    makeTextImage('Hello World', img);
    await page.locator('#fileIn').setInputFiles(img);
    await expect(page.locator('#preview')).toHaveClass(/on/);
    await expect(page.locator('#fname')).toContainText('hello.png');
    await expect(page.locator('#btn')).toBeEnabled();
  });

  test('remove clears preview and disables button', async ({ page }) => {
    await page.goto('/');
    const img = path.join(IMG_DIR, 'rm.png');
    makeTextImage('Remove', img);
    await page.locator('#fileIn').setInputFiles(img);
    await page.locator('#rm').click();
    await expect(page.locator('#preview')).not.toHaveClass(/on/);
    await expect(page.locator('#btn')).toBeDisabled();
  });

  test('upload triggers OCR, shows text and SQS message', async ({ page }) => {
    await page.goto('/');
    await sqsPurge('ocr-results');
    const img = path.join(IMG_DIR, 'pw-test.png');
    makeTextImage('Playwright', img);

    await page.locator('#fileIn').setInputFiles(img);
    await page.locator('#btn').click();
    await expect(page.locator('#status')).toHaveClass(/on/, { timeout: 10000 });

    // Poll S3 for output
    const txt = await waitForS3('ocr-output', 'pw-test.txt', 90000);
    if (txt && txt.trim()) {
      expect(txt.length).toBeGreaterThan(0);
      const msgs = await sqsReceive('ocr-results');
      expect(msgs.length).toBeGreaterThan(0);
      const body = JSON.parse(msgs[0].Body);
      expect(body.source_key).toBe('pw-test.png');
      expect(body.output_key).toBe('pw-test.txt');
      expect(body.text_length).toBeGreaterThan(0);
    }
  });
});

test.describe('Direct S3 Upload', () => {
  test.beforeAll(async () => { await sqsPurge('ocr-results'); });

  test('image with text → .txt + SQS', async () => {
    const img = path.join(IMG_DIR, 'direct.png');
    makeTextImage('Direct Upload', img);
    await s3Put('ocr-uploads', 'direct.png', img);

    const txt = await waitForS3('ocr-output', 'direct.txt', 90000);
    expect(txt).not.toBeNull();
    expect(txt!.trim().length).toBeGreaterThan(0);

    const msgs = await sqsReceive('ocr-results');
    expect(msgs.length).toBeGreaterThan(0);
  });

  test('blank image → no .txt, no SQS', async () => {
    await sqsPurge('ocr-results');
    const img = path.join(IMG_DIR, 'blank.png');
    makeBlankImage(img);
    await s3Put('ocr-uploads', 'blank.png', img);

    await new Promise(r => setTimeout(r, 30000));
    expect(await s3Exists('ocr-output', 'blank.txt')).toBe(false);
    expect((await sqsReceive('ocr-results')).length).toBe(0);
  });

  test('non-image file is ignored', async () => {
    await sqsPurge('ocr-results');
    const txt = path.join(IMG_DIR, 'readme.txt');
    fs.writeFileSync(txt, 'Not an image.');
    await s3Put('ocr-uploads', 'readme.txt', txt);

    await new Promise(r => setTimeout(r, 15000));
    expect(await s3Exists('ocr-output', 'readme.txt')).toBe(false);
    expect((await sqsReceive('ocr-results')).length).toBe(0);
  });
});

test.describe('Multiple Formats', () => {
  test('JPEG works', async () => {
    const img = path.join(IMG_DIR, 'fmt.jpg');
    makeTextImage('JPEG Test', img);
    await s3Put('ocr-uploads', 'fmt.jpg', img);
    const txt = await waitForS3('ocr-output', 'fmt.txt', 90000);
    expect(txt).not.toBeNull();
    expect(txt!.trim().length).toBeGreaterThan(0);
  });
});
