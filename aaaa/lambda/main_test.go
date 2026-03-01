package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

// ── Mock S3 ──

type mockS3 struct {
	getBody       []byte
	uploadedFiles map[string]string
}

func newMockS3(img []byte) *mockS3 {
	return &mockS3{getBody: img, uploadedFiles: make(map[string]string)}
}

func (m *mockS3) GetObject(_ context.Context, p *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(m.getBody))}, nil
}

func (m *mockS3) PutObject(_ context.Context, p *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	buf := new(bytes.Buffer)
	buf.ReadFrom(p.Body)
	m.uploadedFiles[*p.Key] = buf.String()
	return &s3.PutObjectOutput{}, nil
}

// ── Mock SQS ──

type mockSQS struct{ messages []string }

func (m *mockSQS) GetQueueUrl(_ context.Context, _ *sqs.GetQueueUrlInput, _ ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error) {
	return &sqs.GetQueueUrlOutput{QueueUrl: aws.String("http://localhost:4566/000000000000/ocr-results")}, nil
}

func (m *mockSQS) SendMessage(_ context.Context, p *sqs.SendMessageInput, _ ...func(*sqs.Options)) (*sqs.SendMessageOutput, error) {
	m.messages = append(m.messages, *p.MessageBody)
	return &sqs.SendMessageOutput{MessageId: aws.String("test-id")}, nil
}

// ── Tests ──

func TestDeriveOutputKey(t *testing.T) {
	cases := map[string]string{
		"photo.png":                "photo.txt",
		"uploads/image.jpg":       "uploads/image.txt",
		"path/to/scan.tiff":       "path/to/scan.txt",
		"file.name.with.dots.png": "file.name.with.dots.txt",
	}
	for in, want := range cases {
		if got := deriveOutputKey(in); got != want {
			t.Errorf("deriveOutputKey(%q)=%q want %q", in, got, want)
		}
	}
}

func TestIsImageFile(t *testing.T) {
	yes := []string{"a.png", "b.PNG", "c.jpg", "d.jpeg", "e.tiff", "f.tif", "g.bmp", "h.gif", "i.webp"}
	no := []string{"a.pdf", "b.txt", "c.go", "noext"}
	for _, f := range yes {
		if !isImageFile(f) {
			t.Errorf("expected %q to be image", f)
		}
	}
	for _, f := range no {
		if isImageFile(f) {
			t.Errorf("expected %q to NOT be image", f)
		}
	}
}

func TestProcessImage_WithText(t *testing.T) {
	orig := RunTesseract
	defer func() { RunTesseract = orig }()
	RunTesseract = func(_ string) (string, error) { return "Hello OCR", nil }

	ms3 := newMockS3([]byte("fake-img"))
	msqs := &mockSQS{}
	p := &Processor{s3Client: ms3, sqsClient: msqs, queueURL: "http://q"}

	if err := p.processImage(context.Background(), "ocr-uploads", "test.png"); err != nil {
		t.Fatal(err)
	}

	if txt, ok := ms3.uploadedFiles["test.txt"]; !ok {
		t.Fatal("no txt uploaded")
	} else if txt != "Hello OCR" {
		t.Errorf("got %q", txt)
	}

	if len(msqs.messages) != 1 {
		t.Fatalf("want 1 msg, got %d", len(msqs.messages))
	}
	var msg SQSMessage
	json.Unmarshal([]byte(msqs.messages[0]), &msg)
	if msg.OutputKey != "test.txt" || msg.TextLength != 9 {
		t.Errorf("bad msg: %+v", msg)
	}
}

func TestProcessImage_NoText(t *testing.T) {
	orig := RunTesseract
	defer func() { RunTesseract = orig }()
	RunTesseract = func(_ string) (string, error) { return "   \n  \n", nil }

	ms3 := newMockS3([]byte("fake-img"))
	msqs := &mockSQS{}
	p := &Processor{s3Client: ms3, sqsClient: msqs, queueURL: "http://q"}

	if err := p.processImage(context.Background(), "ocr-uploads", "blank.png"); err != nil {
		t.Fatal(err)
	}
	if len(ms3.uploadedFiles) != 0 {
		t.Error("should not upload for blank image")
	}
	if len(msqs.messages) != 0 {
		t.Error("should not send SQS for blank image")
	}
}

func TestSQSMessageJSON(t *testing.T) {
	msg := SQSMessage{"b1", "k1", "b2", "k2", 42}
	data, _ := json.Marshal(msg)
	var parsed SQSMessage
	json.Unmarshal(data, &parsed)
	if parsed != msg {
		t.Errorf("roundtrip failed: %+v", parsed)
	}
}
