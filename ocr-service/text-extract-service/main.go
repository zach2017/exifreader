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
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	sqstypes "github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

// FileUploadedMessage is received from the upload service.
type FileUploadedMessage struct {
	Type        string `json:"type"`
	DocumentID  string `json:"document_id"`
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	S3Key       string `json:"s3_key"`
}

// OCRMessage is sent to the OCR service queue.
type OCRMessage struct {
	Type         string `json:"type"`
	DocumentID   string `json:"document_id"`
	DocumentType string `json:"document_type"`
	S3Bucket     string `json:"s3_bucket"`
	S3Key        string `json:"s3_key"`
	ImageIndex   int    `json:"image_index,omitempty"`
	Timestamp    string `json:"timestamp"`
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

	log.Println("Text Extract Service started. Polling for messages...")
	pollMessages()
}

func waitForResources() {
	bucket := os.Getenv("S3_UPLOAD_BUCKET")
	queueURL := os.Getenv("SQS_FILE_QUEUE_URL")

	log.Printf("Waiting for S3 bucket '%s' and SQS queue...", bucket)
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
	queueURL := os.Getenv("SQS_FILE_QUEUE_URL")

	for {
		result, err := sqsClient.ReceiveMessage(context.TODO(), &sqs.ReceiveMessageInput{
			QueueUrl:            aws.String(queueURL),
			MaxNumberOfMessages: 1,
			WaitTimeSeconds:     20,
			VisibilityTimeout:   300, // 5 minutes for processing
		})
		if err != nil {
			log.Printf("Error receiving messages: %v", err)
			time.Sleep(5 * time.Second)
			continue
		}

		for _, msg := range result.Messages {
			processMessage(msg, queueURL)
		}
	}
}

func processMessage(msg sqstypes.Message, queueURL string) {
	var fileMsg FileUploadedMessage
	if err := json.Unmarshal([]byte(*msg.Body), &fileMsg); err != nil {
		log.Printf("Failed to parse message: %v", err)
		deleteMessage(queueURL, msg.ReceiptHandle)
		return
	}

	if fileMsg.Type != "file_uploaded" {
		log.Printf("Ignoring message type: %s", fileMsg.Type)
		deleteMessage(queueURL, msg.ReceiptHandle)
		return
	}

	log.Printf("Processing document %s (file: %s, type: %s)",
		fileMsg.DocumentID, fileMsg.Filename, fileMsg.ContentType)

	err := processDocument(fileMsg)
	if err != nil {
		log.Printf("Error processing document %s: %v", fileMsg.DocumentID, err)
	} else {
		log.Printf("Successfully processed document %s", fileMsg.DocumentID)
	}

	deleteMessage(queueURL, msg.ReceiptHandle)
}

func processDocument(msg FileUploadedMessage) error {
	// Download file from S3
	tmpDir, err := os.MkdirTemp("", "extract-"+msg.DocumentID)
	if err != nil {
		return fmt.Errorf("failed to create temp dir: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	ext := strings.ToLower(filepath.Ext(msg.Filename))
	localPath := filepath.Join(tmpDir, "input"+ext)

	if err := downloadFromS3(os.Getenv("S3_UPLOAD_BUCKET"), msg.S3Key, localPath); err != nil {
		return fmt.Errorf("failed to download from S3: %w", err)
	}

	fileType := categorizeFile(ext, msg.ContentType)
	log.Printf("Document %s categorized as: %s", msg.DocumentID, fileType)

	switch fileType {
	case "pdf":
		return processPDF(msg, localPath, tmpDir)
	case "word":
		return processWord(msg, localPath, tmpDir)
	case "rtf":
		return processRTF(msg, localPath, tmpDir)
	case "image":
		return processImage(msg)
	default:
		return fmt.Errorf("unsupported file type: %s", ext)
	}
}

// categorizeFile determines the file category based on extension and content type.
func categorizeFile(ext, contentType string) string {
	switch ext {
	case ".pdf":
		return "pdf"
	case ".doc", ".docx":
		return "word"
	case ".rtf":
		return "rtf"
	case ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif":
		return "image"
	}

	// Fallback to content type
	if strings.Contains(contentType, "pdf") {
		return "pdf"
	}
	if strings.Contains(contentType, "word") || strings.Contains(contentType, "msword") {
		return "word"
	}
	if strings.Contains(contentType, "rtf") {
		return "rtf"
	}
	if strings.HasPrefix(contentType, "image/") {
		return "image"
	}

	return "unknown"
}

// ─── PDF Processing ────────────────────────────────────────────────────────────

func processPDF(msg FileUploadedMessage, localPath, tmpDir string) error {
	// Step 1: Extract text from PDF
	log.Printf("[%s] Extracting text from PDF...", msg.DocumentID)

	textPath := filepath.Join(tmpDir, "extracted.txt")
	cmd := exec.Command("pdftotext", "-layout", localPath, textPath)
	if output, err := cmd.CombinedOutput(); err != nil {
		log.Printf("[%s] pdftotext output: %s", msg.DocumentID, string(output))
		return fmt.Errorf("pdftotext failed: %w", err)
	}

	// Upload extracted text to S3
	extractedKey := fmt.Sprintf("%s.txt", msg.DocumentID)
	if err := uploadToS3(os.Getenv("S3_EXTRACTED_BUCKET"), extractedKey, textPath); err != nil {
		return fmt.Errorf("failed to upload extracted text: %w", err)
	}
	log.Printf("[%s] Text saved to s3://%s/%s", msg.DocumentID, os.Getenv("S3_EXTRACTED_BUCKET"), extractedKey)

	// Step 2: Extract images from PDF for OCR
	log.Printf("[%s] Extracting images from PDF...", msg.DocumentID)

	imageDir := filepath.Join(tmpDir, "images")
	os.MkdirAll(imageDir, 0755)
	imagePrefix := filepath.Join(imageDir, "img")

	cmd = exec.Command("pdfimages", "-png", localPath, imagePrefix)
	if output, err := cmd.CombinedOutput(); err != nil {
		log.Printf("[%s] pdfimages output (non-fatal): %s", msg.DocumentID, string(output))
		// Not fatal — PDF may have no images
		return nil
	}

	// Find extracted images
	imageFiles, err := filepath.Glob(filepath.Join(imageDir, "img-*.png"))
	if err != nil || len(imageFiles) == 0 {
		log.Printf("[%s] No images found in PDF", msg.DocumentID)
		return nil
	}

	log.Printf("[%s] Found %d images in PDF, sending to OCR...", msg.DocumentID, len(imageFiles))

	// Upload each image to tmp-files and send OCR message
	for i, imgPath := range imageFiles {
		imgKey := fmt.Sprintf("%s/image-%03d.png", msg.DocumentID, i+1)
		if err := uploadToS3(os.Getenv("S3_TMP_BUCKET"), imgKey, imgPath); err != nil {
			log.Printf("[%s] Failed to upload image %d: %v", msg.DocumentID, i+1, err)
			continue
		}

		ocrMsg := OCRMessage{
			Type:         "ocr_needed",
			DocumentID:   msg.DocumentID,
			DocumentType: "pdf_image",
			S3Bucket:     os.Getenv("S3_TMP_BUCKET"),
			S3Key:        imgKey,
			ImageIndex:   i + 1,
			Timestamp:    time.Now().UTC().Format(time.RFC3339),
		}
		if err := sendOCRMessage(ocrMsg); err != nil {
			log.Printf("[%s] Failed to queue OCR for image %d: %v", msg.DocumentID, i+1, err)
		} else {
			log.Printf("[%s] Queued OCR for image %d/%d", msg.DocumentID, i+1, len(imageFiles))
		}
	}

	return nil
}

// ─── Word Processing ───────────────────────────────────────────────────────────

func processWord(msg FileUploadedMessage, localPath, tmpDir string) error {
	log.Printf("[%s] Extracting text from Word document...", msg.DocumentID)

	textPath := filepath.Join(tmpDir, "extracted.txt")
	ext := strings.ToLower(filepath.Ext(msg.Filename))

	var cmd *exec.Cmd
	if ext == ".docx" {
		// Use pandoc for .docx
		cmd = exec.Command("pandoc", "-f", "docx", "-t", "plain", "--wrap=none", "-o", textPath, localPath)
	} else {
		// Use antiword for .doc
		cmd = exec.Command("sh", "-c", fmt.Sprintf("antiword '%s' > '%s'", localPath, textPath))
	}

	if output, err := cmd.CombinedOutput(); err != nil {
		log.Printf("[%s] Word extraction output: %s", msg.DocumentID, string(output))
		// Try pandoc as fallback for .doc too
		if ext == ".doc" {
			cmd = exec.Command("pandoc", "-f", "doc", "-t", "plain", "--wrap=none", "-o", textPath, localPath)
			if output2, err2 := cmd.CombinedOutput(); err2 != nil {
				log.Printf("[%s] Fallback pandoc output: %s", msg.DocumentID, string(output2))
				return fmt.Errorf("word extraction failed: %w", err)
			}
		} else {
			return fmt.Errorf("word extraction failed: %w", err)
		}
	}

	extractedKey := fmt.Sprintf("%s.txt", msg.DocumentID)
	if err := uploadToS3(os.Getenv("S3_EXTRACTED_BUCKET"), extractedKey, textPath); err != nil {
		return fmt.Errorf("failed to upload extracted text: %w", err)
	}
	log.Printf("[%s] Text saved to s3://%s/%s", msg.DocumentID, os.Getenv("S3_EXTRACTED_BUCKET"), extractedKey)

	return nil
}

// ─── RTF Processing ────────────────────────────────────────────────────────────

func processRTF(msg FileUploadedMessage, localPath, tmpDir string) error {
	log.Printf("[%s] Extracting text from RTF...", msg.DocumentID)

	textPath := filepath.Join(tmpDir, "extracted.txt")

	// Try unrtf first, fallback to pandoc
	cmd := exec.Command("sh", "-c",
		fmt.Sprintf("unrtf --text '%s' | tail -n +4 > '%s'", localPath, textPath))

	if output, err := cmd.CombinedOutput(); err != nil {
		log.Printf("[%s] unrtf output (trying pandoc): %s", msg.DocumentID, string(output))
		cmd = exec.Command("pandoc", "-f", "rtf", "-t", "plain", "--wrap=none", "-o", textPath, localPath)
		if output2, err2 := cmd.CombinedOutput(); err2 != nil {
			log.Printf("[%s] pandoc output: %s", msg.DocumentID, string(output2))
			return fmt.Errorf("RTF extraction failed: %w", err2)
		}
	}

	extractedKey := fmt.Sprintf("%s.txt", msg.DocumentID)
	if err := uploadToS3(os.Getenv("S3_EXTRACTED_BUCKET"), extractedKey, textPath); err != nil {
		return fmt.Errorf("failed to upload extracted text: %w", err)
	}
	log.Printf("[%s] Text saved to s3://%s/%s", msg.DocumentID, os.Getenv("S3_EXTRACTED_BUCKET"), extractedKey)

	return nil
}

// ─── Image Processing (send to OCR) ────────────────────────────────────────────

func processImage(msg FileUploadedMessage) error {
	log.Printf("[%s] Image file detected, sending to OCR service...", msg.DocumentID)

	ext := strings.ToLower(filepath.Ext(msg.Filename))
	imageType := strings.TrimPrefix(ext, ".")

	ocrMsg := OCRMessage{
		Type:         "ocr_needed",
		DocumentID:   msg.DocumentID,
		DocumentType: imageType,
		S3Bucket:     os.Getenv("S3_UPLOAD_BUCKET"),
		S3Key:        msg.S3Key,
		ImageIndex:   0,
		Timestamp:    time.Now().UTC().Format(time.RFC3339),
	}

	return sendOCRMessage(ocrMsg)
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

func uploadToS3(bucket, key, localPath string) error {
	data, err := os.ReadFile(localPath)
	if err != nil {
		return err
	}

	_, err = s3Client.PutObject(context.TODO(), &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(key),
		Body:        bytes.NewReader(data),
		ContentType: aws.String("text/plain"),
	})
	return err
}

// ─── SQS Helpers ───────────────────────────────────────────────────────────────

func sendOCRMessage(msg OCRMessage) error {
	msgBytes, err := json.Marshal(msg)
	if err != nil {
		return err
	}

	queueURL := os.Getenv("SQS_OCR_QUEUE_URL")
	_, err = sqsClient.SendMessage(context.TODO(), &sqs.SendMessageInput{
		QueueUrl:    aws.String(queueURL),
		MessageBody: aws.String(string(msgBytes)),
	})
	return err
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
