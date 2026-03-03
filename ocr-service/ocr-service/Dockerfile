FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod ./
RUN go mod download 2>/dev/null || true
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o /ocr-service .

FROM alpine:3.19
RUN apk --no-cache add \
    ca-certificates \
    curl \
    tesseract-ocr \
    tesseract-ocr-data-eng \
    poppler-utils
COPY --from=builder /ocr-service /ocr-service
CMD ["/ocr-service"]
