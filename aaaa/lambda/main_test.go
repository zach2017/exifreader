package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"testing"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

// ──────────────────────────────────────────────
// Mock S3 Client
// ──────────────────────────────────────────────

type mockS3Client struct {
	getObjectFunc func(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	putObjectFunc func(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	uploadedFiles map[string]string // key → body content
}

func newMockS3(imageData []byte) *mockS3Client {
	m := &mockS3Client{
		uploadedFiles: make(map[string]string),
	}
	m.getObjectFunc = func(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
		return &s3.GetObjectOutput{
			Body:          io.NopCloser(bytes.NewReader(imageData)),
			ContentLength: aws.Int64(int64(len(imageData))),
			ContentType:   aws.String("image/png"),
		}, nil
	}
	m.putObjectFunc = func(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
		buf := new(bytes.Buffer)
		buf.ReadFrom(params.Body)
		m.uploadedFiles[*params.Key] = buf.String()
		return &s3.PutObjectOutput{}, nil
	}
	return m
}

func (m *mockS3Client) GetObject(ctx context.Context, params *s3.GetObjectInput, optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	return m.getObjectFunc(ctx, params, optFns...)
}

func (m *mockS3Client) PutObject(ctx context.Context, params *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	return m.putObjectFunc(ctx, params, optFns...)
}

// ──────────────────────────────────────────────
// Mock SQS Client
// ──────────────────────────────────────────────

type mockSQSClient struct {
	messages []string
}

func (m *mockSQSClient) GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput, optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
	return &sqs.GetQueueUrlOutput{
		QueueUrl: aws.String("http://localhost:4566/000000000000/ocr-results"),
	}, nil
}

func (m *mockSQSClient) SendMessage(ctx context.Context, params *sqs.SendMessageInput, optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error) {
	m.messages = append(m.messages, *params.MessageBody)
	return &sqs.SendMessageOutput{
		MessageId: aws.String("mock-message-id"),
	}, nil
}

// ──────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────

func TestDeriveOutputKey(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"photo.png", "photo.txt"},
		{"uploads/image.jpg", "uploads/image.txt"},
		{"path/to/scan.tiff", "path/to/scan.txt"},
		{"no-ext", "no-ext.txt"},
		{"file.name.with.dots.png", "file.name.with.dots.txt"},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := deriveOutputKey(tt.input)
			if result != tt.expected {
				t.Errorf("deriveOutputKey(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestIsImageFile(t *testing.T) {
	tests := []struct {
		input    string
		expected bool
	}{
		{"photo.png", true},
		{"photo.PNG", true},
		{"image.jpg", true},
		{"image.jpeg", true},
		{"scan.tiff", true},
		{"scan.tif", true},
		{"image.bmp", true},
		{"image.gif", true},
		{"image.webp", true},
		{"document.pdf", false},
		{"file.txt", false},
		{"script.go", false},
		{"noextension", false},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := isImageFile(tt.input)
			if result != tt.expected {
				t.Errorf("isImageFile(%q) = %v, want %v", tt.input, result, tt.expected)
			}
		})
	}
}

func TestProcessImage_WithText(t *testing.T) {
	// Mock tesseract to return extracted text
	originalRunTesseract := RunTesseract
	defer func() { RunTesseract = originalRunTesseract }()

	extractedText := "Hello World from OCR"
	RunTesseract = func(imagePath string) (string, error) {
		return extractedText, nil
	}

	mockS3 := newMockS3([]byte("fake-image-data"))
	mockSQS := &mockSQSClient{}

	processor := &OCRProcessor{
		s3Client:  mockS3,
		sqsClient: mockSQS,
		queueURL:  "http://localhost:4566/000000000000/ocr-results",
	}

	ctx := context.Background()
	err := processor.ProcessImage(ctx, "ocr-uploads", "test-image.png")
	if err != nil {
		t.Fatalf("ProcessImage failed: %v", err)
	}

	// Verify text file was uploaded
	uploadedText, ok := mockS3.uploadedFiles["test-image.txt"]
	if !ok {
		t.Fatal("Expected text file to be uploaded to S3")
	}
	if uploadedText != extractedText {
		t.Errorf("Uploaded text = %q, want %q", uploadedText, extractedText)
	}

	// Verify SQS message was sent
	if len(mockSQS.messages) != 1 {
		t.Fatalf("Expected 1 SQS message, got %d", len(mockSQS.messages))
	}

	var msg SQSMessage
	if err := json.Unmarshal([]byte(mockSQS.messages[0]), &msg); err != nil {
		t.Fatalf("Failed to parse SQS message: %v", err)
	}
	if msg.SourceBucket != "ocr-uploads" {
		t.Errorf("SourceBucket = %q, want %q", msg.SourceBucket, "ocr-uploads")
	}
	if msg.OutputKey != "test-image.txt" {
		t.Errorf("OutputKey = %q, want %q", msg.OutputKey, "test-image.txt")
	}
	if msg.TextLength != len(extractedText) {
		t.Errorf("TextLength = %d, want %d", msg.TextLength, len(extractedText))
	}
}

func TestProcessImage_NoText(t *testing.T) {
	// Mock tesseract to return empty string
	originalRunTesseract := RunTesseract
	defer func() { RunTesseract = originalRunTesseract }()

	RunTesseract = func(imagePath string) (string, error) {
		return "   \n\n  ", nil // whitespace only
	}

	mockS3 := newMockS3([]byte("fake-image-data"))
	mockSQS := &mockSQSClient{}

	processor := &OCRProcessor{
		s3Client:  mockS3,
		sqsClient: mockSQS,
		queueURL:  "http://localhost:4566/000000000000/ocr-results",
	}

	ctx := context.Background()
	err := processor.ProcessImage(ctx, "ocr-uploads", "blank-image.png")
	if err != nil {
		t.Fatalf("ProcessImage failed: %v", err)
	}

	// Verify NO file was uploaded
	if len(mockS3.uploadedFiles) != 0 {
		t.Errorf("Expected no files uploaded, got %d", len(mockS3.uploadedFiles))
	}

	// Verify NO SQS message was sent
	if len(mockSQS.messages) != 0 {
		t.Errorf("Expected no SQS messages, got %d", len(mockSQS.messages))
	}
}

func TestHandleS3Event_SkipsNonImages(t *testing.T) {
	// This test verifies that non-image files are skipped.
	// We use the event directly — the handler would need a real processor,
	// so we test the isImageFile logic used in the handler.
	event := events.S3Event{
		Records: []events.S3EventRecord{
			{
				S3: events.S3Entity{
					Bucket: events.S3Bucket{Name: "ocr-uploads"},
					Object: events.S3Object{Key: "readme.txt"},
				},
			},
		},
	}

	for _, record := range event.Records {
		key := record.S3.Object.Key
		if isImageFile(key) {
			t.Errorf("Expected %q to be skipped as non-image", key)
		}
	}
}

func TestSQSMessageFormat(t *testing.T) {
	msg := SQSMessage{
		SourceBucket: "ocr-uploads",
		SourceKey:    "test.png",
		OutputBucket: "ocr-output",
		OutputKey:    "test.txt",
		TextLength:   42,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	var parsed SQSMessage
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if parsed.SourceBucket != msg.SourceBucket {
		t.Errorf("SourceBucket mismatch")
	}
	if parsed.TextLength != 42 {
		t.Errorf("TextLength = %d, want 42", parsed.TextLength)
	}
}

// Compile-time interface checks
var _ S3Client = (*mockS3Client)(nil)
var _ SQSClient = (*mockSQSClient)(nil)
var _ S3Client = (*s3.Client)(nil)

// Ensure s3types is used (for compile)
var _ = s3types.BucketLocationConstraintAfSouth1
