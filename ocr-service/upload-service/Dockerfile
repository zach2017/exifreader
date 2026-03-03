FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod ./
RUN go mod download 2>/dev/null || true
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o /upload-service .

FROM alpine:3.19
RUN apk --no-cache add ca-certificates curl
COPY --from=builder /upload-service /upload-service
EXPOSE 8080
CMD ["/upload-service"]
