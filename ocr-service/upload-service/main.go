package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/google/uuid"
)

// SQSMessage represents the message sent when a file is uploaded.
type SQSMessage struct {
	Type        string `json:"type"`
	DocumentID  string `json:"document_id"`
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	S3Key       string `json:"s3_key"`
	Timestamp   string `json:"timestamp"`
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

	http.HandleFunc("/", serveForm)
	http.HandleFunc("/upload", handleUpload)
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})

	log.Println("Upload service listening on :8080")
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func serveForm(w http.ResponseWriter, r *http.Request) {
	html := `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OCR Document Upload</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: #1e293b;
            border-radius: 16px;
            padding: 48px;
            max-width: 560px;
            width: 90%;
            box-shadow: 0 25px 50px rgba(0,0,0,0.4);
        }
        h1 {
            font-size: 1.75rem;
            margin-bottom: 8px;
            color: #f1f5f9;
        }
        .subtitle {
            color: #94a3b8;
            margin-bottom: 32px;
            font-size: 0.95rem;
        }
        .drop-zone {
            border: 2px dashed #334155;
            border-radius: 12px;
            padding: 48px 24px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
            margin-bottom: 24px;
            background: #0f172a;
        }
        .drop-zone:hover, .drop-zone.dragover {
            border-color: #3b82f6;
            background: rgba(59,130,246,0.05);
        }
        .drop-zone .icon { font-size: 2.5rem; margin-bottom: 12px; }
        .drop-zone p { color: #94a3b8; }
        .drop-zone .filename {
            color: #3b82f6;
            font-weight: 600;
            margin-top: 8px;
        }
        .supported {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 24px;
        }
        .supported span {
            background: #334155;
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 0.8rem;
            color: #94a3b8;
        }
        button {
            width: 100%;
            padding: 14px;
            background: #3b82f6;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover { background: #2563eb; }
        button:disabled { background: #334155; cursor: not-allowed; }
        .status {
            margin-top: 16px;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 0.9rem;
            display: none;
        }
        .status.success { display: block; background: rgba(34,197,94,0.1); color: #22c55e; border: 1px solid rgba(34,197,94,0.2); }
        .status.error { display: block; background: rgba(239,68,68,0.1); color: #ef4444; border: 1px solid rgba(239,68,68,0.2); }
        .status.loading { display: block; background: rgba(59,130,246,0.1); color: #3b82f6; border: 1px solid rgba(59,130,246,0.2); }
        input[type="file"] { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>&#128196; Document Upload</h1>
        <p class="subtitle">Upload documents for text extraction and OCR processing</p>

        <form id="uploadForm" enctype="multipart/form-data">
            <div class="drop-zone" id="dropZone">
                <div class="icon">&#128424;</div>
                <p>Drag & drop a file here or <strong style="color:#3b82f6">click to browse</strong></p>
                <p class="filename" id="fileName"></p>
            </div>
            <input type="file" id="fileInput" name="file"
                   accept=".pdf,.doc,.docx,.rtf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.gif">

            <div class="supported">
                <span>PDF</span><span>Word (.doc/.docx)</span><span>RTF</span>
                <span>PNG</span><span>JPEG</span><span>TIFF</span><span>BMP</span>
            </div>

            <button type="submit" id="submitBtn" disabled>Upload & Process</button>
        </form>

        <div class="status" id="status"></div>
    </div>

    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const fileName = document.getElementById('fileName');
        const submitBtn = document.getElementById('submitBtn');
        const status = document.getElementById('status');
        const form = document.getElementById('uploadForm');

        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', e => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                updateFileName();
            }
        });
        fileInput.addEventListener('change', updateFileName);

        function updateFileName() {
            if (fileInput.files.length) {
                fileName.textContent = fileInput.files[0].name;
                submitBtn.disabled = false;
            }
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!fileInput.files.length) return;

            submitBtn.disabled = true;
            submitBtn.textContent = 'Uploading...';
            status.className = 'status loading';
            status.textContent = 'Uploading and processing...';

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);

            try {
                const resp = await fetch('/upload', { method: 'POST', body: formData });
                const data = await resp.json();
                if (resp.ok) {
                    status.className = 'status success';
                    status.textContent = 'Document ' + data.document_id + ' uploaded successfully! Processing started.';
                } else {
                    status.className = 'status error';
                    status.textContent = 'Error: ' + (data.error || 'Upload failed');
                }
            } catch (err) {
                status.className = 'status error';
                status.textContent = 'Network error: ' + err.message;
            }

            submitBtn.disabled = false;
            submitBtn.textContent = 'Upload & Process';
        });
    </script>
</body>
</html>`
	w.Header().Set("Content-Type", "text/html")
	w.Write([]byte(html))
}

func handleUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	r.ParseMultipartForm(50 << 20) // 50MB max

	file, header, err := r.FormFile("file")
	if err != nil {
		jsonError(w, "Failed to read file", http.StatusBadRequest)
		return
	}
	defer file.Close()

	documentID := uuid.New().String()
	ext := strings.ToLower(filepath.Ext(header.Filename))
	s3Key := fmt.Sprintf("%s/%s%s", documentID, documentID, ext)
	bucket := os.Getenv("S3_UPLOAD_BUCKET")

	contentType := header.Header.Get("Content-Type")
	if contentType == "" {
		contentType = detectContentType(ext)
	}

	// Upload to S3
	_, err = s3Client.PutObject(context.TODO(), &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(s3Key),
		Body:        file,
		ContentType: aws.String(contentType),
	})
	if err != nil {
		log.Printf("S3 upload error: %v", err)
		jsonError(w, "Failed to upload to S3", http.StatusInternalServerError)
		return
	}

	log.Printf("Uploaded %s to s3://%s/%s", header.Filename, bucket, s3Key)

	// Send SQS message
	msg := SQSMessage{
		Type:        "file_uploaded",
		DocumentID:  documentID,
		Filename:    header.Filename,
		ContentType: contentType,
		S3Key:       s3Key,
		Timestamp:   time.Now().UTC().Format(time.RFC3339),
	}

	msgBytes, _ := json.Marshal(msg)
	queueURL := os.Getenv("SQS_QUEUE_URL")

	_, err = sqsClient.SendMessage(context.TODO(), &sqs.SendMessageInput{
		QueueUrl:    aws.String(queueURL),
		MessageBody: aws.String(string(msgBytes)),
	})
	if err != nil {
		log.Printf("SQS send error: %v", err)
		jsonError(w, "File uploaded but failed to queue processing", http.StatusInternalServerError)
		return
	}

	log.Printf("Queued processing for document %s", documentID)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"document_id": documentID,
		"status":      "queued",
		"s3_key":      s3Key,
	})
}

func detectContentType(ext string) string {
	types := map[string]string{
		".pdf":  "application/pdf",
		".doc":  "application/msword",
		".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		".rtf":  "application/rtf",
		".png":  "image/png",
		".jpg":  "image/jpeg",
		".jpeg": "image/jpeg",
		".tiff": "image/tiff",
		".tif":  "image/tiff",
		".bmp":  "image/bmp",
		".gif":  "image/gif",
	}
	if ct, ok := types[ext]; ok {
		return ct
	}
	return "application/octet-stream"
}

func jsonError(w http.ResponseWriter, msg string, code int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
