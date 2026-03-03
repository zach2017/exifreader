package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
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
	sqstypes "github.com/aws/aws-sdk-go-v2/service/sqs/types"
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
	log.Printf("Starting upload service with endpoint: %s", endpoint)

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

	// Wait for LocalStack resources to be ready
	waitForResources()

	mux := http.NewServeMux()
	mux.HandleFunc("/", serveForm)
	mux.HandleFunc("/upload", handleUpload)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	// Wrap with recovery middleware
	handler := recoveryMiddleware(mux)

	log.Println("Upload service listening on :8080")
	log.Fatal(http.ListenAndServe(":8080", handler))
}

// waitForResources polls until S3 bucket and SQS queue are available.
func waitForResources() {
	bucket := os.Getenv("S3_UPLOAD_BUCKET")
	queueURL := os.Getenv("SQS_QUEUE_URL")

	log.Printf("Waiting for S3 bucket '%s' and SQS queue...", bucket)

	for i := 0; i < 60; i++ {
		// Check S3 bucket
		_, s3Err := s3Client.HeadBucket(context.TODO(), &s3.HeadBucketInput{
			Bucket: aws.String(bucket),
		})

		// Check SQS queue
		_, sqsErr := sqsClient.GetQueueAttributes(context.TODO(), &sqs.GetQueueAttributesInput{
			QueueUrl:       aws.String(queueURL),
			AttributeNames: []sqstypes.QueueAttributeName{sqstypes.QueueAttributeNameAll},
		})

		if s3Err == nil && sqsErr == nil {
			log.Println("All resources ready!")
			return
		}

		if s3Err != nil {
			log.Printf("  [%d/60] S3 bucket not ready: %v", i+1, s3Err)
		}
		if sqsErr != nil {
			log.Printf("  [%d/60] SQS queue not ready: %v", i+1, sqsErr)
		}
		time.Sleep(2 * time.Second)
	}

	log.Println("WARNING: Timed out waiting for resources, starting anyway...")
}

// recoveryMiddleware catches panics and returns a JSON error instead of crashing.
func recoveryMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("PANIC recovered: %v", rec)
				writeJSON(w, http.StatusInternalServerError, map[string]string{
					"error": fmt.Sprintf("Internal server error: %v", rec),
				})
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// writeJSON safely marshals and writes JSON. This is the ONLY way to write JSON responses.
func writeJSON(w http.ResponseWriter, statusCode int, data interface{}) {
	body, err := json.Marshal(data)
	if err != nil {
		log.Printf("JSON marshal error: %v", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"error":"internal json encoding error"}`))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	w.Write(body)
}

func serveForm(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}

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
            word-break: break-all;
        }
        .status.success { display: block; background: rgba(34,197,94,0.1); color: #22c55e; border: 1px solid rgba(34,197,94,0.2); }
        .status.error   { display: block; background: rgba(239,68,68,0.1); color: #ef4444; border: 1px solid rgba(239,68,68,0.2); }
        .status.loading { display: block; background: rgba(59,130,246,0.1); color: #3b82f6; border: 1px solid rgba(59,130,246,0.2); }
        input[type="file"] { display: none; }
        code { background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; font-size: 0.85em; }
        .debug {
            margin-top: 12px;
            padding: 8px;
            background: #0f172a;
            border-radius: 6px;
            font-family: monospace;
            font-size: 0.75rem;
            color: #64748b;
            max-height: 150px;
            overflow-y: auto;
            display: none;
            white-space: pre-wrap;
            word-break: break-all;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>&#128196; Document Upload</h1>
        <p class="subtitle">Upload documents for text extraction and OCR processing</p>

        <div class="drop-zone" id="dropZone">
            <div class="icon">&#128424;</div>
            <p>Drag &amp; drop a file here or <strong style="color:#3b82f6">click to browse</strong></p>
            <p class="filename" id="fileName"></p>
        </div>
        <input type="file" id="fileInput" name="file"
               accept=".pdf,.doc,.docx,.rtf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.gif">

        <div class="supported">
            <span>PDF</span><span>Word (.doc/.docx)</span><span>RTF</span>
            <span>PNG</span><span>JPEG</span><span>TIFF</span><span>BMP</span>
        </div>

        <button id="submitBtn" disabled>Upload &amp; Process</button>

        <div class="status" id="statusBox"></div>
        <div class="debug" id="debugBox"></div>
    </div>

    <script>
        var dropZone = document.getElementById('dropZone');
        var fileInput = document.getElementById('fileInput');
        var fileNameEl = document.getElementById('fileName');
        var submitBtn = document.getElementById('submitBtn');
        var statusBox = document.getElementById('statusBox');
        var debugBox = document.getElementById('debugBox');

        function debugLog(msg) {
            console.log('[upload]', msg);
            debugBox.style.display = 'block';
            debugBox.textContent += msg + '\n';
            debugBox.scrollTop = debugBox.scrollHeight;
        }

        function showStatus(cls, html) {
            statusBox.className = 'status ' + cls;
            statusBox.innerHTML = html;
        }

        function esc(s) {
            var d = document.createElement('div');
            d.textContent = s;
            return d.innerHTML;
        }

        function formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
            return (bytes/(1024*1024)).toFixed(1) + ' MB';
        }

        dropZone.addEventListener('click', function() { fileInput.click(); });
        dropZone.addEventListener('dragover', function(e) { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', function() { dropZone.classList.remove('dragover'); });
        dropZone.addEventListener('drop', function(e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                onFileSelected();
            }
        });
        fileInput.addEventListener('change', onFileSelected);

        function onFileSelected() {
            if (fileInput.files.length) {
                var f = fileInput.files[0];
                fileNameEl.textContent = f.name + ' (' + formatSize(f.size) + ')';
                submitBtn.disabled = false;
            }
        }

        submitBtn.addEventListener('click', function() {
            if (!fileInput.files.length) return;
            doUpload();
        });

        async function doUpload() {
            debugBox.textContent = '';
            debugBox.style.display = 'none';
            submitBtn.disabled = true;
            submitBtn.textContent = 'Uploading...';
            showStatus('loading', 'Uploading and processing...');

            var theFile = fileInput.files[0];
            var formData = new FormData();
            formData.append('file', theFile);
            debugLog('POST /upload  file=' + theFile.name + '  size=' + theFile.size);

            // Step 1: send the request
            var resp;
            try {
                resp = await fetch('/upload', { method: 'POST', body: formData });
            } catch (netErr) {
                debugLog('NETWORK ERROR: ' + netErr);
                showStatus('error', 'Cannot reach server. Is the upload service running?');
                resetBtn();
                return;
            }
            debugLog('HTTP ' + resp.status + '  content-type=' + (resp.headers.get('content-type') || '(none)'));

            // Step 2: read body as text
            var rawBody;
            try {
                rawBody = await resp.text();
            } catch (readErr) {
                debugLog('BODY READ ERROR: ' + readErr);
                showStatus('error', 'Error reading server response');
                resetBtn();
                return;
            }
            debugLog('Body length=' + rawBody.length);
            debugLog('Body: ' + rawBody.substring(0, 500));

            // Step 3: try JSON parse
            var data;
            try {
                data = JSON.parse(rawBody);
            } catch (jsonErr) {
                debugLog('JSON PARSE ERROR: ' + jsonErr);
                showStatus('error',
                    'Server returned non-JSON response (HTTP ' + resp.status + '):<br><code>' +
                    esc(rawBody.substring(0, 300)) + '</code>');
                resetBtn();
                return;
            }
            debugLog('Parsed OK: ' + JSON.stringify(data));

            // Step 4: display result
            if (resp.status >= 200 && resp.status < 300 && data.document_id) {
                showStatus('success',
                    '<strong>&#10003; Upload successful!</strong><br>' +
                    'Document ID: <code>' + esc(data.document_id) + '</code><br>' +
                    'Status: ' + esc(data.status || 'queued') + '<br>' +
                    'S3 Key: <code>' + esc(data.s3_key || '') + '</code>');
                fileNameEl.textContent = '';
                fileInput.value = '';
            } else {
                showStatus('error', 'Error: ' + esc(data.error || 'Upload failed (HTTP ' + resp.status + ')'));
            }

            resetBtn();
        }

        function resetBtn() {
            submitBtn.disabled = !fileInput.files.length;
            submitBtn.textContent = 'Upload & Process';
        }
    </script>
</body>
</html>`
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(html))
}

func handleUpload(w http.ResponseWriter, r *http.Request) {
	log.Printf("[UPLOAD] %s /upload from %s", r.Method, r.RemoteAddr)

	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed, use POST"})
		return
	}

	// Parse multipart form (50MB limit)
	if err := r.ParseMultipartForm(50 << 20); err != nil {
		log.Printf("[UPLOAD] ParseMultipartForm error: %v", err)
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "File too large or invalid form data: " + err.Error()})
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		log.Printf("[UPLOAD] FormFile error: %v", err)
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "No file provided: " + err.Error()})
		return
	}
	defer file.Close()

	log.Printf("[UPLOAD] File: %s  size=%d  content-type=%s", header.Filename, header.Size, header.Header.Get("Content-Type"))

	documentID := uuid.New().String()
	ext := strings.ToLower(filepath.Ext(header.Filename))
	s3Key := fmt.Sprintf("%s/%s%s", documentID, documentID, ext)
	bucket := os.Getenv("S3_UPLOAD_BUCKET")

	contentType := header.Header.Get("Content-Type")
	if contentType == "" || contentType == "application/octet-stream" {
		contentType = detectContentType(ext)
	}

	// Buffer the file in memory for reliable S3 upload
	var buf bytes.Buffer
	if _, err := io.Copy(&buf, file); err != nil {
		log.Printf("[UPLOAD] Read file error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "Failed to read uploaded file"})
		return
	}

	// Upload to S3
	log.Printf("[UPLOAD] Uploading to s3://%s/%s (%d bytes)", bucket, s3Key, buf.Len())
	_, err = s3Client.PutObject(context.TODO(), &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(s3Key),
		Body:        bytes.NewReader(buf.Bytes()),
		ContentType: aws.String(contentType),
	})
	if err != nil {
		log.Printf("[UPLOAD] S3 PutObject ERROR: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{
			"error": "Failed to upload to S3: " + err.Error(),
		})
		return
	}
	log.Printf("[UPLOAD] S3 upload OK")

	// Build SQS message
	msg := SQSMessage{
		Type:        "file_uploaded",
		DocumentID:  documentID,
		Filename:    header.Filename,
		ContentType: contentType,
		S3Key:       s3Key,
		Timestamp:   time.Now().UTC().Format(time.RFC3339),
	}

	msgBytes, err := json.Marshal(msg)
	if err != nil {
		log.Printf("[UPLOAD] JSON marshal error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "Internal error encoding message"})
		return
	}

	queueURL := os.Getenv("SQS_QUEUE_URL")
	log.Printf("[UPLOAD] Sending SQS message to %s", queueURL)

	_, err = sqsClient.SendMessage(context.TODO(), &sqs.SendMessageInput{
		QueueUrl:    aws.String(queueURL),
		MessageBody: aws.String(string(msgBytes)),
	})
	if err != nil {
		log.Printf("[UPLOAD] SQS SendMessage ERROR: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{
			"error": "File saved to S3 but failed to queue for processing: " + err.Error(),
		})
		return
	}

	log.Printf("[UPLOAD] SUCCESS document_id=%s", documentID)

	writeJSON(w, http.StatusOK, map[string]string{
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
