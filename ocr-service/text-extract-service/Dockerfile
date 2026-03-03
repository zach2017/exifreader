FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod ./
RUN go mod download 2>/dev/null || true
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o /text-extract-service .

FROM alpine:3.19
RUN apk --no-cache add \
    ca-certificates \
    curl \
    poppler-utils \
    pandoc \
    antiword \
    unrtf
COPY --from=builder /text-extract-service /text-extract-service
CMD ["/text-extract-service"]
