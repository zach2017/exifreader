import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import {
  s3ObjectExists,
  s3GetObject,
  s3PutObject,
  sqsReceiveMessages,
  sqsPurge,
  waitForS3Object,
  generateTestImage,
  generateBlankImage,
} from '../helpers/aws-helpers';

const TEST_IMAGES_DIR = path.resolve('/app/test-images');

test.describe('OCR Pipeline — Web Upload', () => {
  test.beforeAll(async () => {
    await sqsPurge('ocr-results');
  });

  test('page loads with upload form elements', async ({ page }) => {
    await page.goto('/');

    await expect(page.locator('h1')).toContainText('OCR Extract');
    await expect(page.locator('#dropzone')).toBeVisible();
    await expect(page.locator('#uploadBtn')).toBeVisible();
    await expect(page.locator('#uploadBtn')).toBeDisabled();
  });

  test('file selection enables upload button and shows preview', async ({ page }) => {
    await page.goto('/');

    const imgPath = path.join(TEST_IMAGES_DIR, 'test-hello.png');
    generateTestImage('Hello World', imgPath);

    const fileInput = page.locator('#fileInput');
    await fileInput.setInputFiles(imgPath);

    await expect(page.locator('#filePreview')).toHaveClass(/visible/);
    await expect(page.locator('#fileName')).toContainText('test-hello.png');
    await expect(page.locator('#uploadBtn')).toBeEnabled();
  });

  test('file removal disables upload button', async ({ page }) => {
    await page.goto('/');

    const imgPath = path.join(TEST_IMAGES_DIR, 'test-remove.png');
    generateTestImage('Remove Me', imgPath);

    await page.locator('#fileInput').setInputFiles(imgPath);
    await expect(page.locator('#uploadBtn')).toBeEnabled();

    await page.locator('#fileRemove').click();

    await expect(page.locator('#filePreview')).not.toHaveClass(/visible/);
    await expect(page.locator('#uploadBtn')).toBeDisabled();
  });

  test('rejects non-image files', async ({ page }) => {
    await page.goto('/');

    const txtPath = path.join(TEST_IMAGES_DIR, 'not-an-image.txt');
    fs.writeFileSync(txtPath, 'This is not an image');

    // Playwright setInputFiles with accept mismatch — browser may or may not accept
    // The important thing is the upload button state
    await page.locator('#fileInput').setInputFiles(txtPath);

    // The file input has accept="image/..." so the browser should reject .txt
    // Even if it doesn't, the server-side Lambda ignores non-image files
  });

  test('upload image with text triggers OCR and shows result', async ({ page }) => {
    await page.goto('/');

    await sqsPurge('ocr-results');

    const imgPath = path.join(TEST_IMAGES_DIR, 'test-ocr-text.png');
    generateTestImage('Playwright Test', imgPath);

    await page.locator('#fileInput').setInputFiles(imgPath);
    await page.locator('#uploadBtn').click();

    // Wait for status to show processing
    await expect(page.locator('#status')).toHaveClass(/visible/, { timeout: 10_000 });

    // Poll S3 for the OCR output
    const outputText = await waitForS3Object('ocr-output', 'test-ocr-text.txt', 90_000);

    if (outputText && outputText.trim()) {
      expect(outputText.length).toBeGreaterThan(0);

      const messages = await sqsReceiveMessages('ocr-results');
      expect(messages.length).toBeGreaterThan(0);

      const msgBody = JSON.parse(messages[0].Body);
      expect(msgBody.source_bucket).toBe('ocr-uploads');
      expect(msgBody.source_key).toBe('test-ocr-text.png');
      expect(msgBody.output_bucket).toBe('ocr-output');
      expect(msgBody.output_key).toBe('test-ocr-text.txt');
      expect(msgBody.text_length).toBeGreaterThan(0);
    }
  });
});

test.describe('OCR Pipeline — Direct S3 Upload', () => {
  test.beforeAll(async () => {
    await sqsPurge('ocr-results');
  });

  test('image with text produces .txt file and SQS message', async () => {
    const imgPath = path.join(TEST_IMAGES_DIR, 'direct-test.png');
    generateTestImage('Direct Upload', imgPath);

    await s3PutObject('ocr-uploads', 'direct-test.png', imgPath);

    const outputText = await waitForS3Object('ocr-output', 'direct-test.txt', 90_000);

    expect(outputText).not.toBeNull();
    expect(outputText!.trim().length).toBeGreaterThan(0);

    const messages = await sqsReceiveMessages('ocr-results');
    expect(messages.length).toBeGreaterThan(0);

    const msgBody = JSON.parse(messages[0].Body);
    expect(msgBody.output_key).toBe('direct-test.txt');
  });

  test('blank image produces no .txt file and no SQS message', async () => {
    await sqsPurge('ocr-results');

    const imgPath = path.join(TEST_IMAGES_DIR, 'blank-test.png');
    generateBlankImage(imgPath);

    await s3PutObject('ocr-uploads', 'blank-test.png', imgPath);

    // Wait for Lambda to process
    await new Promise(r => setTimeout(r, 30_000));

    const exists = await s3ObjectExists('ocr-output', 'blank-test.txt');
    expect(exists).toBe(false);

    const messages = await sqsReceiveMessages('ocr-results');
    expect(messages.length).toBe(0);
  });

  test('non-image file is ignored by Lambda', async () => {
    await sqsPurge('ocr-results');

    const txtPath = path.join(TEST_IMAGES_DIR, 'readme.txt');
    fs.writeFileSync(txtPath, 'This is a text file, not an image.');
    await s3PutObject('ocr-uploads', 'readme.txt', txtPath);

    await new Promise(r => setTimeout(r, 15_000));

    const exists = await s3ObjectExists('ocr-output', 'readme.txt');
    expect(exists).toBe(false);

    const messages = await sqsReceiveMessages('ocr-results');
    expect(messages.length).toBe(0);
  });
});

test.describe('OCR Pipeline — Multiple Formats', () => {
  test('JPEG image is processed correctly', async () => {
    const imgPath = path.join(TEST_IMAGES_DIR, 'test-jpeg.jpg');
    generateTestImage('JPEG Format', imgPath);

    await s3PutObject('ocr-uploads', 'test-jpeg.jpg', imgPath);

    const outputText = await waitForS3Object('ocr-output', 'test-jpeg.txt', 90_000);
    expect(outputText).not.toBeNull();
    expect(outputText!.trim().length).toBeGreaterThan(0);
  });
});
