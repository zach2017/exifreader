# Tesseract OCR API (Go + Docker)

A lightweight OCR microservice using Tesseract and Go, with a CLI client that sends images and prints extracted text to stdout.

## Architecture

```
┌──────────────┐   base64 JSON    ┌──────────────────┐
│  ocr-client  │ ──────────────►  │   ocr-server     │
│  (Go CLI)    │                  │  (Go + Tesseract) │
│              │ ◄────────────── │                    │
└──────────────┘   { "text": …}  └──────────────────┘
```

## Quick Start

### 1. Start the server

```bash
docker compose up -d ocr-server
```

### 2. Run the client with an image

Place your image in the `./images/` directory, then:

```bash
docker compose run --rm ocr-client /images/sample.png
docker compose run --rm ocr-client /images/testimage.jpg

```

The extracted text will be printed to stdout.

### 3. Optionally specify a language

```bash
```

## API Reference

### `POST /ocr`

**Request body:**
```json
{
  "image": "<base64-encoded-image>",
  "language": "eng"
}
```

**Response:**
```json
{
  "text": "Extracted text from the image..."
}
```

### `GET /health`

Returns `{"status": "ok"}`.

## Using with curl

```bash
# Encode image and send directly
BASE64=$(base64 -w0 myimage.png)
curl -s http://localhost:8080/ocr \
  -H "Content-Type: application/json" \
  -d "{\"image\": \"$BASE64\"}" | jq -r .text
```

## Adding Languages

Edit `server/Dockerfile` and add more tesseract language packs:

```dockerfile
RUN apk add --no-cache tesseract-ocr tesseract-ocr-data-eng tesseract-ocr-data-deu tesseract-ocr-data-fra
```

## Project Structure

```
tesseract-ocr-api/
├── docker-compose.yml
├── images/              # Mount point for input images
├── server/
│   ├── Dockerfile
│   ├── go.mod
│   └── main.go          # HTTP server with /ocr endpoint
├── client/
│   ├── Dockerfile
│   ├── go.mod
│   └── main.go          # CLI client: reads file → base64 → POST → stdout
└── README.md
```
