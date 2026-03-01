package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

type OCRRequest struct {
	Image    string `json:"image"`    // base64 encoded image
	Language string `json:"language"` // optional: tesseract language (default "eng")
}

type OCRResponse struct {
	Text  string `json:"text,omitempty"`
	Error string `json:"error,omitempty"`
}

func ocrHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "only POST is allowed")
		return
	}

	var req OCRRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}

	if req.Image == "" {
		writeError(w, http.StatusBadRequest, "image field is required (base64 encoded)")
		return
	}

	lang := req.Language
	if lang == "" {
		lang = "eng"
	}

	// Decode base64 image
	imageData, err := base64.StdEncoding.DecodeString(req.Image)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid base64: "+err.Error())
		return
	}

	// Write to temp file
	tmpDir, err := os.MkdirTemp("", "ocr-*")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to create temp dir: "+err.Error())
		return
	}
	defer os.RemoveAll(tmpDir)

	inputPath := filepath.Join(tmpDir, "input.img")
	if err := os.WriteFile(inputPath, imageData, 0644); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to write image: "+err.Error())
		return
	}

	outputBase := filepath.Join(tmpDir, "output")

	// Run tesseract
	cmd := exec.Command("tesseract", inputPath, outputBase, "-l", lang)
	cmdOutput, err := cmd.CombinedOutput()
	if err != nil {
		writeError(w, http.StatusInternalServerError,
			fmt.Sprintf("tesseract error: %v\noutput: %s", err, string(cmdOutput)))
		return
	}

	// Read result
	textBytes, err := os.ReadFile(outputBase + ".txt")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to read OCR output: "+err.Error())
		return
	}

	text := strings.TrimSpace(string(textBytes))

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(OCRResponse{Text: text})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func writeError(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(OCRResponse{Error: msg})
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	http.HandleFunc("/ocr", ocrHandler)
	http.HandleFunc("/health", healthHandler)

	log.Printf("OCR server listening on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatal(err)
	}
}
