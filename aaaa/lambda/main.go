package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
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

// SQSMessage is sent when OCR succeeds.
type SQSMessage struct {
	SourceBucket string `json:"source_bucket"`
	SourceKey    string `json:"source_key"`
	OutputBucket string `json:"output_bucket"`
	OutputKey    string `json:"output_key"`
	TextLength   int    `json:"text_length"`
}

// S3API interface for testability.
type S3API interface {
	GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

// SQSAPI interface for testability.
type SQSAPI interface {
	GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error)
	SendMessage(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error)
}

// RunTesseract can be overridden in tests.
var RunTesseract = runTesseractReal

func runTesseractReal(imagePath string) (string, error) {
	/* outputBase := strings.TrimSuffix(imagePath, filepath.Ext(imagePath))
	cmd := exec.Command("tesseract", imagePath, outputBase, "--oem", "1", "--psm", "3")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	cmd.Stdout = os.Stdout

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("tesseract failed: %w — stderr: %s", err, stderr.String())
	}

	outputFile := outputBase + ".txt"
	textBytes, err := os.ReadFile(outputFile)
	if err != nil {
		return "", fmt.Errorf("reading tesseract output: %w", err)
	}
	*/
	return "Works", nil
	//return string(textBytes), nil
}

// Processor handles the OCR pipeline.
type Processor struct {
	s3Client  S3API
	sqsClient SQSAPI
	queueURL  string
}

func newProcessor(ctx context.Context) (*Processor, error) {
	endpoint := os.Getenv("AWS_ENDPOINT_URL")
	region := os.Getenv("AWS_DEFAULT_REGION")
	if region == "" {
		region = "us-east-1"
	}

	opts := []func(*config.LoadOptions) error{
		config.WithRegion(region),
	}

	if endpoint != "" {
		log.Printf("Using custom endpoint: %s", endpoint)
		opts = append(opts,
			config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider(
				os.Getenv("AWS_ACCESS_KEY_ID"),
				os.Getenv("AWS_SECRET_ACCESS_KEY"),
				"",
			)),
		)
	}

	cfg, err := config.LoadDefaultConfig(ctx, opts...)
	if err != nil {
		return nil, fmt.Errorf("loading AWS config: %w", err)
	}

	s3Opts := func(o *s3.Options) {
		o.UsePathStyle = true
		if endpoint != "" {
			o.BaseEndpoint = aws.String(endpoint)
		}
	}

	sqsOpts := func(o *sqs.Options) {
		if endpoint != "" {
			o.BaseEndpoint = aws.String(endpoint)
		}
	}

	s3Client := s3.NewFromConfig(cfg, s3Opts)
	sqsClient := sqs.NewFromConfig(cfg, sqsOpts)

	queueResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
		QueueName: aws.String(sqsQueueName),
	})
	if err != nil {
		return nil, fmt.Errorf("getting queue URL: %w", err)
	}

	return &Processor{
		s3Client:  s3Client,
		sqsClient: sqsClient,
		queueURL:  *queueResult.QueueUrl,
	}, nil
}

func (p *Processor) processImage(ctx context.Context, bucket, key string) error {
	log.Printf("Processing: s3://%s/%s", bucket, key)

	// 1. Download image
	localPath, err := p.download(ctx, bucket, key)
	if err != nil {
		return fmt.Errorf("download: %w", err)
	}
	defer os.Remove(localPath)

	// 2. OCR
	text, err := RunTesseract(localPath)
	if err != nil {
		return fmt.Errorf("OCR: %w", err)
	}

	cleaned := strings.TrimSpace(text)
	if cleaned == "" {
		log.Printf("No text found in %s — skipping", key)
		return nil
	}

	log.Printf("Extracted %d chars from %s", len(cleaned), key)

	// 3. Upload .txt
	outKey := deriveOutputKey(key)
	if err := p.upload(ctx, outputBucket, outKey, cleaned); err != nil {
		return fmt.Errorf("upload: %w", err)
	}

	// 4. Send SQS
	if err := p.sendMessage(ctx, bucket, key, outputBucket, outKey, len(cleaned)); err != nil {
		return fmt.Errorf("SQS: %w", err)
	}

	log.Printf("Done: %s → %s", key, outKey)
	return nil
}

func (p *Processor) download(ctx context.Context, bucket, key string) (string, error) {
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

	localPath := filepath.Join(tmpDir, fmt.Sprintf("ocr-input-%d%s", os.Getpid(), ext))
	data, err := io.ReadAll(result.Body)
	if err != nil {
		return "", err
	}

	return localPath, os.WriteFile(localPath, data, 0644)
}

func (p *Processor) upload(ctx context.Context, bucket, key, text string) error {
	_, err := p.s3Client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(key),
		Body:        strings.NewReader(text),
		ContentType: aws.String("text/plain; charset=utf-8"),
	})
	return err
}

func (p *Processor) sendMessage(ctx context.Context, srcBucket, srcKey, outBucket, outKey string, textLen int) error {
	msg := SQSMessage{
		SourceBucket: srcBucket,
		SourceKey:    srcKey,
		OutputBucket: outBucket,
		OutputKey:    outKey,
		TextLength:   textLen,
	}
	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	_, err = p.sqsClient.SendMessage(ctx, &sqs.SendMessageInput{
		QueueUrl:    aws.String(p.queueURL),
		MessageBody: aws.String(string(data)),
	})
	return err
}

func deriveOutputKey(imageKey string) string {
	ext := filepath.Ext(imageKey)
	return strings.TrimSuffix(imageKey, ext) + ".txt"
}

func isImageFile(key string) bool {
	ext := strings.ToLower(filepath.Ext(key))
	switch ext {
	case ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp":
		return true
	}
	return false
}

func handler(ctx context.Context, s3Event events.S3Event) error {
	proc, err := newProcessor(ctx)
	if err != nil {
		return fmt.Errorf("init processor: %w", err)
	}

	for _, record := range s3Event.Records {
		bucket := record.S3.Bucket.Name
		key := record.S3.Object.Key

		if !isImageFile(key) {
			log.Printf("Skipping non-image: %s", key)
			continue
		}

		if err := proc.processImage(ctx, bucket, key); err != nil {
			log.Printf("ERROR %s/%s: %v", bucket, key, err)
			return err
		}
	}
	return nil
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.Printf("OCR Lambda starting — endpoint=%s region=%s",
		os.Getenv("AWS_ENDPOINT_URL"), os.Getenv("AWS_DEFAULT_REGION"))
	lambda.Start(handler)
}
