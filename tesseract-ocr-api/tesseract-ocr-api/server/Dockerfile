# Build stage
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY main.go ./
RUN go build -o ocr-server .

# Runtime stage
FROM alpine:3.19
RUN apk add --no-cache tesseract-ocr tesseract-ocr-data-eng
COPY --from=builder /app/ocr-server /usr/local/bin/ocr-server
EXPOSE 8080
CMD ["ocr-server"]
