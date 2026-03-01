package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
)

type OCRRequest struct {
	Image    string `json:"image"`
	Language string `json:"language,omitempty"`
}

type OCRResponse struct {
	Text  string `json:"text,omitempty"`
	Error string `json:"error,omitempty"`
}

func main() {
	serverURL := os.Getenv("OCR_SERVER_URL")
	if serverURL == "" {
		serverURL = "http://localhost:8080"
	}

	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: %s <image-path> [language]\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  image-path: path to image file\n")
		fmt.Fprintf(os.Stderr, "  language:   tesseract language code (default: eng)\n")
		os.Exit(1)
	}

	imagePath := os.Args[1]
	lang := "eng"
	if len(os.Args) >= 3 {
		lang = os.Args[2]
	}

	// Read and encode image
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		log.Fatalf("Failed to read image %s: %v", imagePath, err)
	}

	b64 := base64.StdEncoding.EncodeToString(imageData)

	// Build request
	reqBody := OCRRequest{
		Image:    b64,
		Language: lang,
	}

	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		log.Fatalf("Failed to marshal request: %v", err)
	}

	// Send to server
	url := serverURL + "/ocr"
	resp, err := http.Post(url, "application/json", bytes.NewReader(jsonData))
	if err != nil {
		log.Fatalf("Failed to connect to OCR server at %s: %v", url, err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Fatalf("Failed to read response: %v", err)
	}

	var ocrResp OCRResponse
	if err := json.Unmarshal(body, &ocrResp); err != nil {
		log.Fatalf("Failed to parse response: %v\nRaw: %s", err, string(body))
	}

	if ocrResp.Error != "" {
		fmt.Fprintf(os.Stderr, "OCR Error: %s\n", ocrResp.Error)
		os.Exit(1)
	}

	// Output extracted text to stdout
	fmt.Println(ocrResp.Text)
}
