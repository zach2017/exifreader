# Build stage
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY main.go ./
RUN go build -o ocr-client .

# Runtime stage
FROM alpine:3.19
COPY --from=builder /app/ocr-client /usr/local/bin/ocr-client
ENTRYPOINT ["ocr-client"]
