package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

const (
	outputBucket = "ocr-output"
	sqsQueueName = "ocr-results"
	tmpDir       = "/tmp"
)

// SQSMessage represents the message sent to SQS when OCR succeeds.
type SQSMessage struct {
	SourceBucket string `json:"source_bucket"`
	SourceKey    string `json:"source_key"`
	OutputBucket string `json:"output_bucket"`
	OutputKey    string `json:"output_key"`
	TextLength   int    `json:"text_length"`
}

// OCRProcessor handles S3 and SQS interactions.
type OCRProcessor struct {
	s3Client  S3Client
	sqsClient SQSClient
	queueURL  string
}

// S3Client interface for testability.
type S3Client interface {
	GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

// SQSClient interface for testability.
type SQSClient interface {
	GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error)
	SendMessage(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error)
}

// RunTesseract is a variable so it can be mocked in tests.
var RunTesseract = func(imagePath string) (string, error) {
	outputBase := strings.TrimSuffix(imagePath, filepath.Ext(imagePath))
	cmd := exec.Command("tesseract", imagePath, outputBase, "--oem", "1", "--psm", "3")
	cmd.Stderr = os.Stderr
	cmd.Stdout = os.Stdout

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("tesseract execution failed: %w", err)
	}

	outputFile := outputBase + ".txt"
	textBytes, err := os.ReadFile(outputFile)
	if err != nil {
		return "", fmt.Errorf("failed to read tesseract output: %w", err)
	}

	return string(textBytes), nil
}

// NewOCRProcessor creates a new processor with real AWS clients.
func NewOCRProcessor(ctx context.Context) (*OCRProcessor, error) {
	endpoint := os.Getenv("AWS_ENDPOINT_URL")
	region := os.Getenv("AWS_DEFAULT_REGION")
	if region == "" {
		region = "us-east-1"
	}

	var cfg aws.Config
	var err error

	if endpoint != "" {
		customResolver := aws.EndpointResolverWithOptionsFunc(
			func(service, resolvedRegion string, options ...interface{}) (aws.Endpoint, error) {
				return aws.Endpoint{
					URL:               endpoint,
					HostnameImmutable: true,
					SigningRegion:     region,
				}, nil
			},
		)
		cfg, err = config.LoadDefaultConfig(ctx,
			config.WithRegion(region),
			config.WithEndpointResolverWithOptions(customResolver),
			config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")),
		)
	} else {
		cfg, err = config.LoadDefaultConfig(ctx, config.WithRegion(region))
	}

	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	s3Client := s3.NewFromConfig(cfg, func(o *s3.Options) {
		o.UsePathStyle = true
	})
	sqsClient := sqs.NewFromConfig(cfg)

	// Get SQS queue URL
	queueResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(sqsQueueName),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to get SQS queue URL: %w", err)
	}

	return &OCRProcessor{
		s3Client:  s3Client,
		sqsClient: sqsClient,
		queueURL:  *queueResult.QueueUrl,
	}, nil
}

// ProcessImage downloads an image from S3, runs OCR, and uploads results.
func (p *OCRProcessor) ProcessImage(ctx context.Context, bucket, key string) error {
	log.Printf("Processing image: s3://%s/%s", bucket, key)

	// 1. Download image from S3
	localPath, err := p.downloadFromS3(ctx, bucket, key)
	if err != nil {
		return fmt.Errorf("download failed: %w", err)
	}
	defer os.Remove(localPath)

	// 2. Run Tesseract OCR
	text, err := RunTesseract(localPath)
	if err != nil {
		return fmt.Errorf("OCR failed: %w", err)
	}

	// 3. Clean and validate extracted text
	cleanedText := strings.TrimSpace(text)
	if cleanedText == "" {
		log.Printf("No text extracted from image %s — skipping upload and SQS message", key)
		return nil
	}

	log.Printf("Extracted %d characters from %s", len(cleanedText), key)

	// 4. Upload text file to S3
	outputKey := deriveOutputKey(key)
	if err := p.uploadToS3(ctx, outputBucket, outputKey, cleanedText); err != nil {
		return fmt.Errorf("upload failed: %w", err)
	}

	// 5. Send SQS message
	if err := p.sendSQSMessage(ctx, bucket, key, outputBucket, outputKey, len(cleanedText)); err != nil {
		return fmt.Errorf("SQS send failed: %w", err)
	}

	log.Printf("Successfully processed %s → %s", key, outputKey)
	return nil
}

func (p *OCRProcessor) downloadFromS3(ctx context.Context, bucket, key string) (string, error) {
	result, err := p.s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return "", err
	}
	defer result.Body.Close()

	ext := filepath.Ext(key)
	if ext == "" {
		ext = ".png"
	}

	localPath := filepath.Join(tmpDir, "ocr-input"+ext)
	buf := new(bytes.Buffer)
	if _, err := buf.ReadFrom(result.Body); err != nil {
		return "", err
	}

	if err := os.WriteFile(localPath, buf.Bytes(), 0644); err != nil {
		return "", err
	}

	return localPath, nil
}

func (p *OCRProcessor) uploadToS3(ctx context.Context, bucket, key, text string) error {
	_, err := p.s3Client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(key),
		Body:        strings.NewReader(text),
		ContentType: aws.String("text/plain; charset=utf-8"),
	})
	return err
}

func (p *OCRProcessor) sendSQSMessage(ctx context.Context, srcBucket, srcKey, outBucket, outKey string, textLen int) error {
	msg := SQSMessage{
		SourceBucket: srcBucket,
		SourceKey:    srcKey,
		OutputBucket: outBucket,
		OutputKey:    outKey,
		TextLength:   textLen,
	}

	msgJSON, err := json.Marshal(msg)
	if err != nil {
		return err
	}

	_, err = p.sqsClient.SendMessage(ctx, &sqs.SendMessageInput{
		QueueUrl:    aws.String(p.queueURL),
		MessageBody: aws.String(string(msgJSON)),
	})
	return err
}

// deriveOutputKey converts an image key to a .txt key.
// e.g., "uploads/photo.png" → "uploads/photo.txt"
func deriveOutputKey(imageKey string) string {
	ext := filepath.Ext(imageKey)
	return strings.TrimSuffix(imageKey, ext) + ".txt"
}

// handleS3Event is the Lambda entry point.
func handleS3Event(ctx context.Context, s3Event events.S3Event) error {
	processor, err := NewOCRProcessor(ctx)
	if err != nil {
		return fmt.Errorf("failed to initialize processor: %w", err)
	}

	for _, record := range s3Event.Records {
		bucket := record.S3.Bucket.Name
		key := record.S3.Object.Key

		// Only process image files
		if !isImageFile(key) {
			log.Printf("Skipping non-image file: %s", key)
			continue
		}

		if err := processor.ProcessImage(ctx, bucket, key); err != nil {
			log.Printf("ERROR processing %s/%s: %v", bucket, key, err)
			return err
		}
	}

	return nil
}

func isImageFile(key string) bool {
	ext := strings.ToLower(filepath.Ext(key))
	switch ext {
	case ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp":
		return true
	}
	return false
}

func main() {
	lambda.Start(handleS3Event)
}
