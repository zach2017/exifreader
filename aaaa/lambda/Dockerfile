# ── Stage 1: Build Go binary ──
FROM golang:1.22-bookworm AS builder

WORKDIR /build
COPY go.mod ./
COPY *.go ./
RUN go mod tidy && go mod download
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -tags lambda.norpc -o bootstrap main.go

# ── Stage 2: Runtime with Tesseract ──
FROM debian:bookworm-slim

# Install Tesseract OCR + English language data
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libtesseract-dev \
        libleptonica-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Verify tesseract installation
RUN tesseract --version

# Copy Lambda bootstrap binary
COPY --from=builder /build/bootstrap /var/runtime/bootstrap

# Lambda runtime interface
WORKDIR /var/task
ENTRYPOINT ["/var/runtime/bootstrap"]
