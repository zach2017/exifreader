package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	sqstypes "github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

// OCRMessage is received from the text-extract service or upload service.
type OCRMessage struct {
	Type         string `json:"type"`
	DocumentID   string `json:"document_id"`
	DocumentType string `json:"document_type"`
	S3Bucket     string `json:"s3_bucket"`
	S3Key        string `json:"s3_key"`
	ImageIndex   int    `json:"image_index,omitempty"`
	Timestamp    string `json:"timestamp"`
}

// OCRCompleteMessage is sent when OCR processing is done.
type OCRCompleteMessage struct {
	Type       string `json:"type"`
	DocumentID string `json:"document_id"`
	S3Bucket   string `json:"s3_bucket"`
	S3Key      string `json:"s3_key"`
	ImageIndex int    `json:"image_index,omitempty"`
	Timestamp  string `json:"timestamp"`
}

var (
	s3Client  *s3.Client
	sqsClient *sqs.Client
)

func main() {
	endpoint := os.Getenv("LOCALSTACK_ENDPOINT")

	customResolver := aws.EndpointResolverWithOptionsFunc(
		func(service, region string, options ...interface{}) (aws.Endpoint, error) {
			return aws.Endpoint{
				URL:               endpoint,
				HostnameImmutable: true,
			}, nil
		},
	)

	cfg, err := config.LoadDefaultConfig(context.TODO(),
		config.WithRegion(os.Getenv("AWS_REGION")),
		config.WithEndpointResolverWithOptions(customResolver),
	)
	if err != nil {
		log.Fatalf("Failed to load AWS config: %v", err)
	}

	s3Client = s3.NewFromConfig(cfg, func(o *s3.Options) {
		o.UsePathStyle = true
	})
	sqsClient = sqs.NewFromConfig(cfg)

	// Wait for LocalStack resources
	waitForResources()

	log.Println("OCR Service started. Polling for messages...")
	pollMessages()
}

func waitForResources() {
	queueURL := os.Getenv("SQS_OCR_QUEUE_URL")
	bucket := os.Getenv("S3_OCR_EXTRACTED_BUCKET")

	log.Printf("Waiting for SQS queue and S3 bucket '%s'...", bucket)
	for i := 0; i < 60; i++ {
		_, s3Err := s3Client.HeadBucket(context.TODO(), &s3.HeadBucketInput{
			Bucket: aws.String(bucket),
		})
		_, sqsErr := sqsClient.GetQueueAttributes(context.TODO(), &sqs.GetQueueAttributesInput{
			QueueUrl:       aws.String(queueURL),
			AttributeNames: []sqstypes.QueueAttributeName{sqstypes.QueueAttributeNameAll},
		})
		if s3Err == nil && sqsErr == nil {
			log.Println("All resources ready!")
			return
		}
		log.Printf("  [%d/60] Waiting... s3=%v sqs=%v", i+1, s3Err, sqsErr)
		time.Sleep(2 * time.Second)
	}
	log.Println("WARNING: Timed out waiting for resources, starting anyway...")
}

func pollMessages() {
	queueURL := os.Getenv("SQS_OCR_QUEUE_URL")

	for {
		result, err := sqsClient.ReceiveMessage(context.TODO(), &sqs.ReceiveMessageInput{
			QueueUrl:            aws.String(queueURL),
			MaxNumberOfMessages: 1,
			WaitTimeSeconds:     20,
			VisibilityTimeout:   600, // 10 minutes for OCR
		})
		if err != nil {
			log.Printf("Error receiving messages: %v", err)
			time.Sleep(5 * time.Second)
			continue
		}

		for _, msg := range result.Messages {
			processOCRMessage(msg, queueURL)
		}
	}
}

func processOCRMessage(msg sqstypes.Message, queueURL string) {
	var ocrMsg OCRMessage
	if err := json.Unmarshal([]byte(*msg.Body), &ocrMsg); err != nil {
		log.Printf("Failed to parse message: %v", err)
		deleteMessage(queueURL, msg.ReceiptHandle)
		return
	}

	if ocrMsg.Type != "ocr_needed" {
		log.Printf("Ignoring message type: %s", ocrMsg.Type)
		deleteMessage(queueURL, msg.ReceiptHandle)
		return
	}

	log.Printf("OCR request for document %s (type: %s, image: %d)",
		ocrMsg.DocumentID, ocrMsg.DocumentType, ocrMsg.ImageIndex)

	if err := performOCR(ocrMsg); err != nil {
		log.Printf("OCR failed for document %s: %v", ocrMsg.DocumentID, err)
	} else {
		log.Printf("OCR completed for document %s", ocrMsg.DocumentID)
	}

	deleteMessage(queueURL, msg.ReceiptHandle)
}

func performOCR(msg OCRMessage) error {
	// Create temp directory
	tmpDir, err := os.MkdirTemp("", "ocr-"+msg.DocumentID)
	if err != nil {
		return fmt.Errorf("failed to create temp dir: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	// Determine input file extension
	ext := filepath.Ext(msg.S3Key)
	if ext == "" {
		ext = "." + msg.DocumentType
	}
	inputPath := filepath.Join(tmpDir, "input"+ext)

	// Download from S3
	log.Printf("[%s] Downloading from s3://%s/%s", msg.DocumentID, msg.S3Bucket, msg.S3Key)
	if err := downloadFromS3(msg.S3Bucket, msg.S3Key, inputPath); err != nil {
		return fmt.Errorf("failed to download from S3: %w", err)
	}

	// If the source is a PDF (original PDF sent for OCR), convert to images first
	if msg.DocumentType == "pdf" {
		return ocrPDF(msg, inputPath, tmpDir)
	}

	// For image files, run tesseract directly
	return ocrImage(msg, inputPath, tmpDir)
}

// ocrPDF converts a PDF to images, then OCRs each page.
func ocrPDF(msg OCRMessage, inputPath, tmpDir string) error {
	log.Printf("[%s] Converting PDF to images for OCR...", msg.DocumentID)

	// Convert PDF pages to images using pdftoppm
	imagePrefix := filepath.Join(tmpDir, "page")
	cmd := exec.Command("pdftoppm", "-png", "-r", "300", inputPath, imagePrefix)
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("pdftoppm failed: %s - %w", string(output), err)
	}

	// Find generated page images
	pageImages, err := filepath.Glob(filepath.Join(tmpDir, "page-*.png"))
	if err != nil || len(pageImages) == 0 {
		return fmt.Errorf("no page images generated from PDF")
	}

	log.Printf("[%s] PDF has %d pages to OCR", msg.DocumentID, len(pageImages))

	var allText bytes.Buffer
	for i, pagePath := range pageImages {
		log.Printf("[%s] OCR page %d/%d...", msg.DocumentID, i+1, len(pageImages))

		outputBase := filepath.Join(tmpDir, fmt.Sprintf("ocr-page-%03d", i+1))
		cmd := exec.Command("tesseract", pagePath, outputBase, "-l", "eng", "--psm", "1")
		if output, err := cmd.CombinedOutput(); err != nil {
			log.Printf("[%s] Tesseract warning page %d: %s", msg.DocumentID, i+1, string(output))
			// Continue with other pages
			continue
		}

		// Read the OCR output
		textData, err := os.ReadFile(outputBase + ".txt")
		if err != nil {
			log.Printf("[%s] Failed to read OCR output page %d: %v", msg.DocumentID, i+1, err)
			continue
		}

		allText.WriteString(fmt.Sprintf("--- Page %d ---\n", i+1))
		allText.Write(textData)
		allText.WriteString("\n\n")
	}

	// Save combined OCR text
	outputKey := fmt.Sprintf("%s.txt", msg.DocumentID)
	if err := uploadTextToS3(os.Getenv("S3_OCR_EXTRACTED_BUCKET"), outputKey, allText.Bytes()); err != nil {
		return fmt.Errorf("failed to upload OCR text: %w", err)
	}

	log.Printf("[%s] OCR text saved to s3://%s/%s",
		msg.DocumentID, os.Getenv("S3_OCR_EXTRACTED_BUCKET"), outputKey)

	// Send OCR complete message
	return sendOCRComplete(msg.DocumentID, os.Getenv("S3_OCR_EXTRACTED_BUCKET"), outputKey, 0)
}

// ocrImage runs Tesseract on a single image file.
func ocrImage(msg OCRMessage, inputPath, tmpDir string) error {
	log.Printf("[%s] Running Tesseract OCR on image...", msg.DocumentID)

	outputBase := filepath.Join(tmpDir, "ocr-output")
	cmd := exec.Command("tesseract", inputPath, outputBase, "-l", "eng", "--psm", "1")
	if output, err := cmd.CombinedOutput(); err != nil {
		// Try with different PSM mode
		log.Printf("[%s] Tesseract attempt 1: %s", msg.DocumentID, string(output))
		cmd = exec.Command("tesseract", inputPath, outputBase, "-l", "eng", "--psm", "3")
		if output2, err2 := cmd.CombinedOutput(); err2 != nil {
			return fmt.Errorf("tesseract failed: %s - %w", string(output2), err2)
		}
	}

	// Read OCR output
	textData, err := os.ReadFile(outputBase + ".txt")
	if err != nil {
		return fmt.Errorf("failed to read OCR output: %w", err)
	}

	// Determine output key
	var outputKey string
	if msg.ImageIndex > 0 {
		// This is an image extracted from a PDF
		outputKey = fmt.Sprintf("%s-image-%03d.txt", msg.DocumentID, msg.ImageIndex)
	} else {
		// This is a standalone image upload
		outputKey = fmt.Sprintf("%s.txt", msg.DocumentID)
	}

	// Upload to tmp-extracted-text bucket
	ocrBucket := os.Getenv("S3_OCR_EXTRACTED_BUCKET")
	if err := uploadTextToS3(ocrBucket, outputKey, textData); err != nil {
		return fmt.Errorf("failed to upload OCR text: %w", err)
	}

	log.Printf("[%s] OCR text saved to s3://%s/%s", msg.DocumentID, ocrBucket, outputKey)

	// Send OCR complete message
	return sendOCRComplete(msg.DocumentID, ocrBucket, outputKey, msg.ImageIndex)
}

// ─── S3 Helpers ────────────────────────────────────────────────────────────────

func downloadFromS3(bucket, key, localPath string) error {
	result, err := s3Client.GetObject(context.TODO(), &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return err
	}
	defer result.Body.Close()

	file, err := os.Create(localPath)
	if err != nil {
		return err
	}
	defer file.Close()

	_, err = io.Copy(file, result.Body)
	return err
}

func uploadTextToS3(bucket, key string, data []byte) error {
	_, err := s3Client.PutObject(context.TODO(), &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(key),
		Body:        bytes.NewReader(data),
		ContentType: aws.String("text/plain; charset=utf-8"),
	})
	return err
}

// ─── SQS Helpers ───────────────────────────────────────────────────────────────

func sendOCRComplete(documentID, bucket, key string, imageIndex int) error {
	msg := OCRCompleteMessage{
		Type:       "ocr_complete",
		DocumentID: documentID,
		S3Bucket:   bucket,
		S3Key:      key,
		ImageIndex: imageIndex,
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
	}

	msgBytes, err := json.Marshal(msg)
	if err != nil {
		return err
	}

	queueURL := os.Getenv("SQS_OCR_COMPLETE_QUEUE_URL")
	_, err = sqsClient.SendMessage(context.TODO(), &sqs.SendMessageInput{
		QueueUrl:    aws.String(queueURL),
		MessageBody: aws.String(string(msgBytes)),
	})
	if err != nil {
		return fmt.Errorf("failed to send ocr_complete: %w", err)
	}

	log.Printf("[%s] Sent ocr_complete message", documentID)
	return nil
}

func deleteMessage(queueURL string, receiptHandle *string) {
	_, err := sqsClient.DeleteMessage(context.TODO(), &sqs.DeleteMessageInput{
		QueueUrl:      aws.String(queueURL),
		ReceiptHandle: receiptHandle,
	})
	if err != nil {
		log.Printf("Failed to delete message: %v", err)
	}
}
