# OCR Document Processing Pipeline

A microservices-based document processing system built with Go, Docker Compose, and LocalStack (S3 + SQS).

## Architecture

```
┌─────────────────┐       ┌──────────────┐       ┌─────────────────────┐
│   Upload Form   │──────▶│  S3: uploads │       │  SQS: file-processing│
│  (localhost:8080)│       └──────────────┘       └──────────┬──────────┘
│                 │──────────────────────────────────────────▶│
└─────────────────┘                                          │
                                                             ▼
                                                ┌────────────────────────┐
                                                │  Text Extract Service  │
                                                │                        │
                                                │  PDF  → pdftotext      │
                                                │  Word → pandoc/antiword│
                                                │  RTF  → unrtf/pandoc   │
                                                │  Image→ send to OCR    │
                                                └────────┬───────────────┘
                                                         │
                              ┌───────────────────┬──────┴──────────┐
                              │                   │                 │
                              ▼                   ▼                 ▼
                    ┌──────────────────┐  ┌──────────────┐  ┌───────────────────┐
                    │ S3: extracted-text│  │ S3: tmp-files│  │ SQS: ocr-processing│
                    │ (.txt files)     │  │ (PDF images) │  └────────┬──────────┘
                    └──────────────────┘  └──────────────┘           │
                                                                     ▼
                                                          ┌──────────────────┐
                                                          │   OCR Service    │
                                                          │   (Tesseract)    │
                                                          └────────┬─────────┘
                                                                   │
                                                    ┌──────────────┴──────────────┐
                                                    ▼                             ▼
                                          ┌──────────────────────┐  ┌───────────────────┐
                                          │S3: tmp-extracted-text│  │ SQS: ocr-complete │
                                          │ (OCR .txt files)     │  └───────────────────┘
                                          └──────────────────────┘
```

## Services

### 1. Upload Service (port 8080)
- Serves HTML drag-and-drop upload form
- Uploads files to S3 `uploads` bucket
- Sends `file_uploaded` message to SQS `file-processing` queue

### 2. Text Extract Service
- Polls `file-processing` SQS queue
- **PDF files**: Extracts text via `pdftotext` → saves to `extracted-text` bucket, extracts embedded images via `pdfimages` → uploads to `tmp-files` bucket → sends `ocr_needed` for each image
- **Word files** (.doc/.docx): Extracts text via `pandoc`/`antiword` → saves to `extracted-text` bucket
- **RTF files**: Extracts text via `unrtf`/`pandoc` → saves to `extracted-text` bucket
- **Image files**: Sends `ocr_needed` message to `ocr-processing` queue

### 3. OCR Service
- Polls `ocr-processing` SQS queue
- Downloads image from S3
- Runs Tesseract OCR (eng language, 300 DPI for PDFs)
- Saves extracted text to `tmp-extracted-text` bucket
- Sends `ocr_complete` message to `ocr-complete` queue

## S3 Buckets

| Bucket | Purpose |
|--------|---------|
| `uploads` | Original uploaded files |
| `extracted-text` | Text extracted from PDF/Word/RTF |
| `tmp-files` | Intermediate files (images from PDFs) |
| `tmp-extracted-text` | OCR-extracted text from images |

## SQS Queues

| Queue | Message Types |
|-------|--------------|
| `file-processing` | `file_uploaded` |
| `ocr-processing` | `ocr_needed` |
| `ocr-complete` | `ocr_complete` |

## Message Formats

### file_uploaded
```json
{
  "type": "file_uploaded",
  "document_id": "uuid",
  "filename": "report.pdf",
  "content_type": "application/pdf",
  "s3_key": "uuid/uuid.pdf",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### ocr_needed
```json
{
  "type": "ocr_needed",
  "document_id": "uuid",
  "document_type": "png",
  "s3_bucket": "uploads",
  "s3_key": "uuid/uuid.png",
  "image_index": 0,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### ocr_complete
```json
{
  "type": "ocr_complete",
  "document_id": "uuid",
  "s3_bucket": "tmp-extracted-text",
  "s3_key": "uuid.txt",
  "image_index": 0,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

## Quick Start

```bash
# Start everything
make up

# Open browser
open http://localhost:8080

# Watch logs
make logs

# Check results
make list-extracted
make list-ocr
```

## Useful Commands

```bash
make up              # Build and start all services
make down            # Stop and remove containers + volumes
make logs            # Follow all service logs
make logs-extract    # Follow text-extract service logs
make logs-ocr        # Follow OCR service logs
make list-buckets    # List all S3 buckets
make list-extracted  # List files in extracted-text bucket
make list-ocr        # List files in tmp-extracted-text bucket
make check-queues    # Show SQS queue depths

# Get extracted text for a document
make get-text DOC_ID=<your-uuid>
make get-ocr-text DOC_ID=<your-uuid>
```

## Processing Flow Examples

### PDF Upload
1. File uploaded to `s3://uploads/{docId}/{docId}.pdf`
2. Text Extract Service: `pdftotext` → `s3://extracted-text/{docId}.txt`
3. Text Extract Service: `pdfimages` → `s3://tmp-files/{docId}/image-001.png`
4. OCR Service: `tesseract` → `s3://tmp-extracted-text/{docId}-image-001.txt`
5. `ocr_complete` sent to SQS

### Image Upload (PNG/JPEG)
1. File uploaded to `s3://uploads/{docId}/{docId}.png`
2. Text Extract Service sends `ocr_needed` to SQS
3. OCR Service: `tesseract` → `s3://tmp-extracted-text/{docId}.txt`
4. `ocr_complete` sent to SQS

### Word/RTF Upload
1. File uploaded to `s3://uploads/{docId}/{docId}.docx`
2. Text Extract Service: `pandoc` → `s3://extracted-text/{docId}.txt`

## Requirements
- Docker & Docker Compose
- AWS CLI (optional, for inspection commands)

# OCR Document Processing Pipeline — Complete Tutorial

## A Comprehensive Guide for Java Developers Learning Go

---

# Table of Contents

1. [Introduction](#1-introduction)
2. [Architecture Overview](#2-architecture-overview)
3. [Go Fundamentals for Java Developers](#3-go-fundamentals-for-java-developers)
4. [Docker & Infrastructure Setup](#4-docker--infrastructure-setup)
5. [Service 1: Init Service — Line-by-Line](#5-service-1-init-service)
6. [Service 2: Upload Service — Line-by-Line](#6-service-2-upload-service)
7. [Service 3: Text Extract Service — Line-by-Line](#7-service-3-text-extract-service)
8. [Service 4: OCR Service — Line-by-Line](#8-service-4-ocr-service)
9. [Coding Decisions: Pros and Cons](#9-coding-decisions-pros-and-cons)
10. [Go vs Java Comparison Summary](#10-go-vs-java-comparison-summary)
11. [Running the Application](#11-running-the-application)

---

# 1. Introduction

This application is a **microservices-based document processing pipeline** that accepts file uploads (PDF, Word, RTF, images), extracts text from them, and performs OCR (Optical Character Recognition) on images. It is built entirely in Go and uses Docker Compose with LocalStack to simulate AWS S3 (file storage) and SQS (message queues) locally.

The pipeline follows an **event-driven architecture**: services communicate exclusively through SQS messages and store data in S3 buckets, rather than calling each other directly.

## What This Tutorial Covers

This tutorial explains **every line of Go code** in the project, written specifically for a developer who understands Java but is new to Go. Every Go concept is mapped to its Java equivalent, and every design decision includes a "Pros & Cons" analysis.

## Prerequisites

- Docker & Docker Compose installed
- Basic understanding of AWS S3 (like a file system) and SQS (like a JMS queue)
- Java development experience

---

# 2. Architecture Overview

```
                    ┌───────────────┐
                    │  Web Browser  │
                    │  (HTML Form)  │
                    └──────┬────────┘
                           │ HTTP POST /upload
                           ▼
┌──────────────────────────────────────────────────────────┐
│                   Upload Service (:8080)                  │
│  1. Saves file to S3 "uploads" bucket                    │
│  2. Sends "file_uploaded" message to SQS                 │
└──────────────────────────────────────────────────────────┘
                           │
                    SQS: file-processing
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│               Text Extract Service                        │
│                                                          │
│  Receives "file_uploaded", determines file type:         │
│                                                          │
│  PDF ──→ pdftotext ──→ S3 "extracted-text" bucket        │
│     └──→ pdfimages ──→ S3 "tmp-files" bucket             │
│                    └──→ SQS "ocr_needed" per image       │
│                                                          │
│  Word (.doc/.docx) ──→ pandoc/antiword ──→ S3            │
│  RTF ──→ unrtf/pandoc ──→ S3                             │
│  Image ──→ SQS "ocr_needed"                              │
└──────────────────────────────────────────────────────────┘
                           │
                    SQS: ocr-processing
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                    OCR Service                            │
│                                                          │
│  Receives "ocr_needed":                                  │
│  1. Downloads image from S3                              │
│  2. Runs Tesseract OCR                                   │
│  3. Saves .txt to S3 "tmp-extracted-text"                │
│  4. Sends "ocr_complete" to SQS                          │
└──────────────────────────────────────────────────────────┘
```

## Startup Order

```
localstack (healthy) → init-service (creates buckets + queues, exits)
                     → upload-service, text-extract-service, ocr-service (start together)
```

## S3 Buckets

| Bucket | Purpose | Java Analogy |
|--------|---------|--------------|
| `uploads` | Original uploaded files | Like a file server's inbox directory |
| `extracted-text` | Text extracted from PDF/Word/RTF | Output directory for processed results |
| `tmp-files` | Intermediate files (images from PDFs) | Temp working directory |
| `tmp-extracted-text` | OCR-extracted text from images | Secondary output directory |

## SQS Queues

| Queue | Message Type | Java Analogy |
|-------|-------------|--------------|
| `file-processing` | `file_uploaded` | JMS Queue with `TextMessage` |
| `ocr-processing` | `ocr_needed` | JMS Queue for OCR work items |
| `ocr-complete` | `ocr_complete` | JMS Queue for completion notifications |

---

# 3. Go Fundamentals for Java Developers

Before diving into the code, here is every Go concept used in this project mapped to Java.

## 3.1 Package Declaration

```go
package main    // Go: every file starts with a package declaration
```

**Java equivalent:**
```java
package com.example.uploadservice;  // Java package
```

**Key difference:** In Go, `package main` is special — it means "this is an executable program." Every Go executable must have a `main` package with a `main()` function. This is like Java requiring a `public static void main(String[] args)` method, but in Go the package name itself signals "executable."

In Go, ALL files in the same directory MUST have the same package name. There are no sub-packages within a directory.

## 3.2 Imports

```go
import (
    "bytes"           // Standard library: byte buffer operations
    "context"         // Standard library: cancellation/timeout propagation
    "encoding/json"   // Standard library: JSON marshal/unmarshal
    "fmt"             // Standard library: formatted I/O (like printf)
    "io"              // Standard library: I/O interfaces
    "log"             // Standard library: logging
    "net/http"        // Standard library: HTTP server and client
    "os"              // Standard library: operating system functions
    "path/filepath"   // Standard library: file path manipulation
    "strings"         // Standard library: string utilities
    "time"            // Standard library: time and duration

    // Third-party packages (fetched by module system)
    "github.com/aws/aws-sdk-go-v2/aws"         // AWS core types
    "github.com/aws/aws-sdk-go-v2/config"       // AWS config loader
    "github.com/aws/aws-sdk-go-v2/service/s3"   // AWS S3 client
    "github.com/aws/aws-sdk-go-v2/service/sqs"  // AWS SQS client
    sqstypes "github.com/aws/aws-sdk-go-v2/service/sqs/types"  // Aliased import
    "github.com/google/uuid"                     // UUID generation
)
```

**Java equivalent:**
```java
import java.io.*;                              // "io"
import java.nio.file.*;                        // "os", "path/filepath"
import com.fasterxml.jackson.databind.*;        // "encoding/json"
import software.amazon.awssdk.services.s3.*;    // S3 client
import software.amazon.awssdk.services.sqs.*;   // SQS client
import java.util.UUID;                          // UUID
```

**Key differences:**

| Concept | Go | Java |
|---------|-----|------|
| Import path | URL-like: `"github.com/aws/..."` | Dot-separated: `software.amazon.awssdk...` |
| Aliasing | `sqstypes "github.com/aws/.../types"` | Not directly possible (use static imports) |
| Unused imports | **Compile error** | Warning only |
| Dependency management | `go.mod` (like `pom.xml`) | `pom.xml` (Maven) or `build.gradle` |

**The alias `sqstypes`:** Go requires unique names. Since both `s3` and `sqs` packages have a `types` sub-package, we alias one with `sqstypes` to avoid collision. In Java, you'd use the fully qualified name.

## 3.3 Struct Types (Go's Version of Classes)

```go
type SQSMessage struct {
    Type        string `json:"type"`
    DocumentID  string `json:"document_id"`
    Filename    string `json:"filename"`
    ContentType string `json:"content_type"`
    S3Key       string `json:"s3_key"`
    Timestamp   string `json:"timestamp"`
}
```

**Java equivalent:**
```java
// Java: a POJO with Jackson annotations
public class SQSMessage {
    @JsonProperty("type")
    private String type;

    @JsonProperty("document_id")
    private String documentId;

    @JsonProperty("filename")
    private String filename;

    @JsonProperty("content_type")
    private String contentType;

    @JsonProperty("s3_key")
    private String s3Key;

    @JsonProperty("timestamp")
    private String timestamp;

    // Getters and setters...
}
```

**Key differences:**

- **No classes in Go.** Go has `struct` (data) and functions. There is no inheritance.
- **Struct tags** (the backtick strings like `` `json:"type"` ``): These are metadata annotations read at runtime by the `encoding/json` package. They are like Java's `@JsonProperty`.
- **Exported vs unexported:** In Go, capitalization controls visibility. `Type` (capital T) is public (exported). `type` (lowercase) would be private (unexported). There are no `public`/`private`/`protected` keywords.
- **No getters/setters needed.** Go accesses fields directly: `msg.Type` not `msg.getType()`.
- **The `omitempty` tag:** `json:"image_index,omitempty"` means "omit this field from JSON if it's zero." Java equivalent is `@JsonInclude(Include.NON_DEFAULT)`.

## 3.4 Variables and Type Inference

```go
// Package-level variables (like Java static fields)
var (
    s3Client  *s3.Client     // Pointer to S3 client
    sqsClient *sqs.Client    // Pointer to SQS client
)

// Inside functions:
endpoint := os.Getenv("LOCALSTACK_ENDPOINT")    // Short variable declaration
var buf bytes.Buffer                              // Explicit declaration
documentID := uuid.New().String()                 // Inferred as string
```

**Java equivalent:**
```java
// Static fields
private static S3Client s3Client;
private static SqsClient sqsClient;

// Inside methods:
String endpoint = System.getenv("LOCALSTACK_ENDPOINT");
ByteArrayOutputStream buf = new ByteArrayOutputStream();
String documentId = UUID.randomUUID().toString();
```

**Key differences:**

- **`:=`** is Go's "short variable declaration." It declares AND assigns in one step, inferring the type. There is no Java equivalent — Java requires `var` (Java 10+) or the explicit type.
- **`*s3.Client`** is a pointer. In Java, all objects are implicitly references (pointers). In Go, you must be explicit: `*T` means "pointer to T", `&x` means "address of x", `*p` means "value that p points to."
- **`var` block:** `var ( ... )` groups multiple declarations. Like Java's multiple field declarations but grouped with parentheses.

## 3.5 Functions and Multiple Return Values

```go
func handleUpload(w http.ResponseWriter, r *http.Request) {
    // w and r are parameters (like Java method parameters)
}

// Multiple return values (Go's most distinctive feature):
cfg, err := config.LoadDefaultConfig(context.TODO())
if err != nil {
    log.Fatalf("Failed: %v", err)
}
```

**Java equivalent:**
```java
void handleUpload(HttpServletResponse w, HttpServletRequest r) {
    // Same concept, different types
}

// Java doesn't have multiple returns. You'd use try-catch:
try {
    SdkClientConfiguration cfg = loadConfig();
} catch (Exception e) {
    logger.error("Failed: {}", e.getMessage());
    System.exit(1);
}
```

**Key difference: Error handling.** This is the biggest difference between Go and Java:

| Aspect | Go | Java |
|--------|-----|------|
| Error mechanism | Return `error` as second value | Throw `Exception` |
| Handling | `if err != nil { ... }` | `try { ... } catch (Exception e) { ... }` |
| Unchecked errors | **Compile warning** (unused variable) | Unchecked exceptions can be ignored |
| Stack traces | Not included by default | Always included |
| Philosophy | "Errors are values" — handle them explicitly | "Errors are exceptional" — throw them up |

In Go, almost every function returns `(result, error)`. You MUST check `err != nil` after every call. This produces verbose code but makes error handling explicit and impossible to accidentally ignore.

## 3.6 The `context.Context` Pattern

```go
_, err := s3Client.PutObject(context.TODO(), &s3.PutObjectInput{...})
```

In Go, `context.Context` is passed as the first argument to nearly every function that does I/O or could be long-running. It carries cancellation signals, timeouts, and request-scoped values.

**Java equivalent:**
```java
// Java doesn't have a universal context pattern.
// Closest equivalents:
Future<PutObjectResponse> future = s3Client.putObject(request);  // async
// Or using thread interruption
if (Thread.currentThread().isInterrupted()) { throw new InterruptedException(); }
```

`context.TODO()` means "I know I should pass a context, but I haven't set one up yet." It's a placeholder. In production code, you'd derive contexts from HTTP requests with timeouts:

```go
ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
defer cancel()
_, err := s3Client.PutObject(ctx, &s3.PutObjectInput{...})
```

## 3.7 The `defer` Keyword

```go
file, err := os.Open("data.txt")
if err != nil {
    return err
}
defer file.Close()    // This runs when the function returns, no matter what
// ... use file ...
```

**Java equivalent:**
```java
// Java 7+ try-with-resources:
try (FileInputStream file = new FileInputStream("data.txt")) {
    // ... use file ...
}  // Automatically closed here
```

`defer` schedules a function call to execute when the enclosing function returns. Multiple defers execute in LIFO order (last deferred = first executed). It is Go's version of `try-with-resources` / `finally`, but more flexible because you can defer any function call, not just `Closeable` objects.

## 3.8 Slices (Go's Version of ArrayList)

```go
buckets := []string{"uploads", "extracted-text", "tmp-files"}

for _, bucket := range buckets {
    fmt.Println(bucket)
}
```

**Java equivalent:**
```java
List<String> buckets = List.of("uploads", "extracted-text", "tmp-files");

for (String bucket : buckets) {
    System.out.println(bucket);
}
```

**Key differences:**
- `[]string` is a **slice** — a dynamically-sized view into an array. It's like `ArrayList<String>` but backed by a contiguous array.
- `range` returns two values: `(index, value)`. The `_` is a "blank identifier" meaning "I don't need this value." It's like `(var _, var bucket)` in Java.
- Go has no generics until Go 1.18, and even then they're simpler than Java's. The AWS SDK uses concrete types, not `List<T>`.

## 3.9 Maps

```go
types := map[string]string{
    ".pdf":  "application/pdf",
    ".doc":  "application/msword",
}

if ct, ok := types[ext]; ok {
    return ct
}
```

**Java equivalent:**
```java
Map<String, String> types = Map.of(
    ".pdf", "application/pdf",
    ".doc", "application/msword"
);

if (types.containsKey(ext)) {
    return types.get(ext);
}
```

The **comma-ok idiom** (`ct, ok := types[ext]`) is Go's way of checking if a key exists. `ok` is `true` if found, `false` if not. Java uses `containsKey()` or `getOrDefault()`.

## 3.10 Interfaces (Implicit Implementation)

```go
// Go's http.Handler interface:
type Handler interface {
    ServeHTTP(ResponseWriter, *Request)
}

// ANY type with a ServeHTTP method automatically implements Handler.
// No "implements" keyword needed!
```

**Java equivalent:**
```java
public interface Handler {
    void serveHTTP(ResponseWriter w, Request r);
}

// Must explicitly declare: class MyHandler implements Handler { ... }
```

**Key difference:** Go interfaces are satisfied **implicitly**. If your type has the right methods, it implements the interface automatically. Java requires explicit `implements`. This is called "structural typing" (Go) vs "nominal typing" (Java).

## 3.11 Function Types and Closures

```go
http.HandleFunc("/upload", handleUpload)

// Or with an inline anonymous function (closure):
http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
    writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
})
```

**Java equivalent:**
```java
// Using a method reference:
router.addRoute("/upload", this::handleUpload);

// Or with a lambda:
router.addRoute("/health", (req, resp) -> {
    resp.getWriter().write("{\"status\":\"ok\"}");
});
```

Go functions are first-class values — they can be assigned to variables, passed as arguments, and returned from functions. This is similar to Java 8+ lambdas and method references.

## 3.12 Goroutines (Go's Concurrency Primitive)

While this project doesn't use goroutines explicitly (each service runs a single polling loop), understanding them is essential. The `for { ... }` infinite loop in each service IS the concurrent processing mechanism — it runs in the main goroutine.

```go
// To run something concurrently:
go func() {
    // This runs in a separate goroutine (lightweight thread)
    processMessage(msg)
}()
```

**Java equivalent:**
```java
// Using virtual threads (Java 21):
Thread.startVirtualThread(() -> {
    processMessage(msg);
});

// Or with ExecutorService:
executor.submit(() -> processMessage(msg));
```

**Key difference:** Goroutines are extremely lightweight (~2KB stack vs ~1MB for Java threads). You can run millions of goroutines. Java's virtual threads (Project Loom, Java 21+) are the closest equivalent.

---

# 4. Docker & Infrastructure Setup

## 4.1 docker-compose.yml — Line by Line

```yaml
version: "3.8"                          # Docker Compose file format version
```
Specifies the Compose file schema version. Like a Maven POM `modelVersion`.

```yaml
services:
  localstack:
    image: localstack/localstack:3.0    # Pre-built Docker image from Docker Hub
    container_name: localstack          # Explicit container name (otherwise auto-generated)
    ports:
      - "4566:4566"                     # Map host port 4566 to container port 4566
```
LocalStack is a tool that emulates AWS services locally. Port 4566 is the unified endpoint for all AWS services (S3, SQS, etc.). In Java terms, think of it as an embedded AWS mock server like `localstack` or `moto`.

```yaml
    environment:
      - SERVICES=s3,sqs                 # Only start S3 and SQS (faster startup)
      - DEFAULT_REGION=us-east-1        # AWS region
      - SQS_ENDPOINT_STRATEGY=path      # Use path-style URLs for SQS
```
`SQS_ENDPOINT_STRATEGY=path` is **critical**. Without it, SQS uses subdomain-style URLs (`http://sqs.us-east-1.localhost.localstack.cloud:4566/...`) which resolve to `127.0.0.1` — the container itself, not LocalStack. Path-style means `http://localstack:4566/000000000000/queue-name`, which resolves correctly within Docker's network.

```yaml
    volumes:
      - "localstack-data:/var/lib/localstack"    # Persist data between restarts
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4566/_localstack/health"]
      interval: 5s                      # Check every 5 seconds
      timeout: 3s                       # Give up after 3 seconds
      retries: 10                       # Try 10 times before marking unhealthy
```
The healthcheck lets other services wait until LocalStack is ready. This is like a Spring Boot `HealthIndicator` — Docker polls the endpoint and marks the container as "healthy" when it responds.

```yaml
  init-service:
    build: ./init-service               # Build from local Dockerfile
    container_name: init-service
    environment:
      - AWS_REGION=us-east-1
      - AWS_ACCESS_KEY_ID=test          # LocalStack accepts any credentials
      - AWS_SECRET_ACCESS_KEY=test
      - LOCALSTACK_ENDPOINT=http://localstack:4566
    depends_on:
      localstack:
        condition: service_healthy      # Wait for healthcheck to pass
```
The init service creates all S3 buckets and SQS queues, then exits. `depends_on: service_healthy` means Docker won't start this container until LocalStack's healthcheck passes.

```yaml
  upload-service:
    build: ./upload-service
    ports:
      - "8080:8080"
    depends_on:
      init-service:
        condition: service_completed_successfully   # Wait for init to exit with code 0
```
`service_completed_successfully` is the key: the upload service won't start until the init service has finished creating all resources and exited cleanly. If init fails (exit code != 0), the upload service won't start at all.

**Java analogy:** This is like Spring Boot's `@DependsOn` annotation combined with Flyway/Liquibase running database migrations before the application starts.

## 4.2 Dockerfiles — Multi-Stage Builds

Every service uses the same Dockerfile pattern:

```dockerfile
# Stage 1: Build the Go binary
FROM golang:1.22-alpine AS builder      # Start from official Go image
WORKDIR /app                            # Set working directory inside container
COPY go.mod ./                          # Copy dependency file first (Docker layer caching)
RUN go mod download 2>/dev/null || true # Download dependencies (cached if go.mod unchanged)
COPY . .                                # Copy all source code
RUN go mod tidy                         # Resolve any missing dependencies
RUN CGO_ENABLED=0 GOOS=linux go build -o /service-name .  # Compile to static binary
```

- **`CGO_ENABLED=0`**: Disables C library linking. Produces a fully static binary that runs on ANY Linux — no shared libraries needed. Java equivalent: creating a GraalVM native image.
- **`GOOS=linux`**: Cross-compile for Linux (even if building on Mac/Windows).
- **`go build -o /service-name .`**: Compile the `main` package in current directory into a binary. Like `javac` + `jar` but produces a single executable file.

```dockerfile
# Stage 2: Create minimal runtime image
FROM alpine:3.19                        # Tiny Linux image (~5MB vs ~700MB for golang image)
RUN apk --no-cache add ca-certificates  # SSL certificates for HTTPS
COPY --from=builder /service-name /service-name  # Copy ONLY the binary from stage 1
CMD ["/service-name"]                   # Run it
```

**Why multi-stage?** The Go compiler image is ~800MB. The final Alpine image with just the binary is ~15MB. In Java terms, this is like building with a full JDK image, then copying only the JAR to a JRE-slim image — but even more dramatic because Go binaries are self-contained.

**Java equivalent Dockerfile:**
```dockerfile
FROM maven:3.9-eclipse-temurin-21 AS build
COPY pom.xml .
RUN mvn dependency:go-offline
COPY src ./src
RUN mvn package -DskipTests

FROM eclipse-temurin:21-jre-alpine
COPY --from=build target/app.jar /app.jar
CMD ["java", "-jar", "/app.jar"]
```

**Comparison:**

| Aspect | Go | Java |
|--------|-----|------|
| Build output | Single static binary (~10-15MB) | JAR file + JVM runtime (~200MB+) |
| Runtime dependencies | None (static binary) | JRE required |
| Startup time | ~10ms | ~1-5 seconds (Spring Boot) |
| Final image size | ~15-20MB | ~200-300MB |
| Memory usage | ~5-15MB RSS | ~100-300MB heap |

---

# 5. Service 1: Init Service

**Purpose:** Creates all S3 buckets and SQS queues in LocalStack, verifies they exist, then exits. Other services depend on this completing successfully.

**Java analogy:** Like a Flyway migration or a `@PostConstruct` bean that runs SQL `CREATE TABLE` statements before the application starts.

## init-service/main.go — Line by Line

```go
package main
```
This file is the entry point for an executable program. Every Go executable must be in `package main`.

```go
import (
    "context"       // Provides context.Context for cancellation/timeouts
    "fmt"           // Formatted printing (Printf, Sprintf)
    "log"           // Structured logging with timestamps
    "os"            // OS-level functions: environment variables, exit codes
    "time"          // Time operations: Sleep, Duration
```
Standard library imports. Go's standard library is extensive — most of what you'd use Apache Commons or Guava for in Java is built in.

```go
    "github.com/aws/aws-sdk-go-v2/aws"             // Core AWS types (aws.String, etc.)
    "github.com/aws/aws-sdk-go-v2/config"           // AWS config loader
    "github.com/aws/aws-sdk-go-v2/service/s3"       // S3 API client
    s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"  // S3 enum types
    "github.com/aws/aws-sdk-go-v2/service/sqs"      // SQS API client
)
```
AWS SDK v2 for Go. This is the equivalent of `software.amazon.awssdk` in Java (AWS SDK v2). The `s3types` alias avoids naming collision with `sqstypes` (if it were used).

### Package-Level Variables

```go
var (
    buckets = []string{
        "uploads",
        "extracted-text",
        "tmp-files",
        "tmp-extracted-text",
    }

    queues = []string{
        "file-processing",
        "ocr-processing",
        "ocr-complete",
    }
)
```

**Java equivalent:**
```java
private static final List<String> BUCKETS = List.of(
    "uploads", "extracted-text", "tmp-files", "tmp-extracted-text"
);
private static final List<String> QUEUES = List.of(
    "file-processing", "ocr-processing", "ocr-complete"
);
```

`var (...)` is a grouped variable declaration. `[]string{...}` creates a slice literal — Go's equivalent of `List.of(...)` but mutable.

### The main() Function

```go
func main() {
    log.Println("============================================")
    log.Println("  LocalStack Resource Init Service")
    log.Println("============================================")
```
`log.Println` writes to stderr with a timestamp prefix. Like `System.err.println` but with auto-timestamps. Go's `log` package is simpler than Log4j/SLF4J — no log levels by default.

```go
    endpoint := os.Getenv("LOCALSTACK_ENDPOINT")
    region := os.Getenv("AWS_REGION")
    if endpoint == "" {
        endpoint = "http://localstack:4566"
    }
    if region == "" {
        region = "us-east-1"
    }
```
Read environment variables with defaults. `os.Getenv` returns `""` if not set (never `null` — Go strings can't be null).

**Java equivalent:**
```java
String endpoint = Optional.ofNullable(System.getenv("LOCALSTACK_ENDPOINT"))
    .orElse("http://localstack:4566");
```

Go doesn't have `Optional` or `null` for strings. Empty string `""` is the zero value. This is simpler but means you can't distinguish "not set" from "set to empty."

```go
    customResolver := aws.EndpointResolverWithOptionsFunc(
        func(service, reg string, options ...interface{}) (aws.Endpoint, error) {
            return aws.Endpoint{
                URL:               endpoint,
                HostnameImmutable: true,
            }, nil
        },
    )
```

This creates an **endpoint resolver** that redirects all AWS API calls to LocalStack. Without this, the SDK would try to reach real AWS servers.

- **`aws.EndpointResolverWithOptionsFunc`**: A function type that adapts a plain function into the `EndpointResolverWithOptions` interface. This is the "functional interface" pattern — like Java's `@FunctionalInterface`.
- **`func(service, reg string, options ...interface{}) (aws.Endpoint, error)`**: An anonymous function (lambda). `options ...interface{}` is a variadic parameter accepting any type — like Java's `Object... args`.
- **`HostnameImmutable: true`**: Tells the SDK "don't modify this URL." Without it, the SDK might prepend the bucket name as a subdomain (e.g., `http://uploads.localstack:4566`), which would fail in Docker.

**Java equivalent:**
```java
S3Client s3Client = S3Client.builder()
    .endpointOverride(URI.create("http://localstack:4566"))
    .region(Region.US_EAST_1)
    .build();
```

Go's approach is more verbose because the SDK uses a single resolver for all services, while Java's SDK lets you override per-client.

```go
    cfg, err := config.LoadDefaultConfig(context.TODO(),
        config.WithRegion(region),
        config.WithEndpointResolverWithOptions(customResolver),
    )
    if err != nil {
        log.Fatalf("FATAL: Failed to load AWS config: %v", err)
    }
```

Loads AWS configuration (credentials from environment, region, endpoint). The `With...` functions are the **functional options pattern** — Go's alternative to the Builder pattern.

- **`context.TODO()`**: A placeholder context meaning "I should provide a real context but haven't yet."
- **`log.Fatalf`**: Logs the message and calls `os.Exit(1)`. Like `logger.error(...); System.exit(1);` combined.
- **`%v`**: Go's default format verb. Prints any value in a human-readable form. Like Java's `toString()`.

**Java equivalent:**
```java
try {
    SdkClientConfiguration cfg = SdkClientConfiguration.builder()
        .region(Region.US_EAST_1)
        .endpointOverride(URI.create(endpoint))
        .build();
} catch (SdkException e) {
    logger.error("Failed: {}", e.getMessage());
    System.exit(1);
}
```

```go
    s3Client := s3.NewFromConfig(cfg, func(o *s3.Options) {
        o.UsePathStyle = true
    })
    sqsClient := sqs.NewFromConfig(cfg)
```

Creates S3 and SQS clients from the shared config. `UsePathStyle = true` means S3 URLs look like `http://host/bucket/key` instead of `http://bucket.host/key`. This is required for LocalStack.

The `func(o *s3.Options)` is another functional option — it receives a mutable options struct and modifies it. Like Java's `S3Client.builder().pathStyleAccessEnabled(true)`.

```go
    ctx := context.TODO()
```
Creates a context to pass to all AWS API calls. `context.TODO()` is a non-nil, empty context. In production, you'd use `context.Background()` or a context with a timeout.

### Resource Creation Loop

```go
    for _, bucket := range buckets {
        createBucket(ctx, s3Client, bucket)
    }
```

Iterates over the `buckets` slice. `range` returns `(index, value)`. The `_` discards the index since we don't need it.

**Java equivalent:**
```java
for (String bucket : buckets) {
    createBucket(s3Client, bucket);
}
```

### createBucket Function

```go
func createBucket(ctx context.Context, client *s3.Client, name string) {
```
Function signature. `ctx context.Context` is Go convention — context is always the first parameter. `client *s3.Client` is a pointer to the S3 client.

```go
    _, err := client.HeadBucket(ctx, &s3.HeadBucketInput{
        Bucket: aws.String(name),
    })
    if err == nil {
        log.Printf("  Bucket '%s' already exists, skipping", name)
        return
    }
```

**Idempotency check:** `HeadBucket` is like HTTP HEAD — it checks if the bucket exists without downloading anything. If `err == nil`, the bucket already exists (from a previous run), so we skip creation.

- **`aws.String(name)`**: Converts a `string` to `*string` (pointer to string). The AWS SDK uses pointers for optional fields. In Java SDK v2, these are just `String` (nullable).
- **`&s3.HeadBucketInput{...}`**: Creates a struct and takes its address (`&`). The `&` is like Java's `new` — it allocates on the heap and returns a pointer.

**Java equivalent:**
```java
try {
    s3Client.headBucket(HeadBucketRequest.builder().bucket(name).build());
    logger.info("Bucket '{}' already exists", name);
    return;
} catch (NoSuchBucketException e) {
    // Bucket doesn't exist, create it
}
```

Notice how Java uses exceptions for control flow here, while Go uses the error return value. This is a fundamental philosophical difference.

```go
    _, err = client.CreateBucket(ctx, &s3.CreateBucketInput{
        Bucket: aws.String(name),
        CreateBucketConfiguration: &s3types.CreateBucketConfiguration{
            LocationConstraint: s3types.BucketLocationConstraintUsEast2,
        },
    })
    if err != nil {
        _, err = client.CreateBucket(ctx, &s3.CreateBucketInput{
            Bucket: aws.String(name),
        })
    }
```

Creates the bucket. The first attempt includes a `LocationConstraint`; if that fails (LocalStack sometimes rejects it), it retries without. This is defensive programming for LocalStack compatibility.

### createQueue Function

```go
func createQueue(ctx context.Context, client *sqs.Client, name string) {
    existing, err := client.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{
        QueueName: aws.String(name),
    })
    if err == nil && existing.QueueUrl != nil {
        log.Printf("  Queue '%s' already exists: %s", name, *existing.QueueUrl)
        return
    }
```

Checks if the queue already exists using `GetQueueUrl`. The `*existing.QueueUrl` dereferences the pointer — since `QueueUrl` is `*string`, we use `*` to get the actual string value for printing.

```go
    result, err := client.CreateQueue(ctx, &sqs.CreateQueueInput{
        QueueName: aws.String(name),
        Attributes: map[string]string{
            "VisibilityTimeout":             "300",
            "MessageRetentionPeriod":        "86400",
            "ReceiveMessageWaitTimeSeconds": "20",
        },
    })
```

Creates the queue with attributes:
- **`VisibilityTimeout: 300`**: After a consumer receives a message, it's hidden from other consumers for 5 minutes (300 seconds). If not deleted within that time, it reappears. Like JMS's redelivery delay.
- **`MessageRetentionPeriod: 86400`**: Messages are kept for 24 hours (86400 seconds) before being automatically deleted.
- **`ReceiveMessageWaitTimeSeconds: 20`**: Enables **long polling** — the `ReceiveMessage` call blocks for up to 20 seconds waiting for messages instead of returning immediately. This reduces empty responses and API costs.

### Verification Section

```go
    allOK := true

    listResult, err := s3Client.ListBuckets(ctx, &s3.ListBucketsInput{})
    if err != nil {
        log.Printf("  ERROR listing buckets: %v", err)
        allOK = false
    } else {
        for _, b := range listResult.Buckets {
            log.Printf("  ✓ %s", *b.Name)
        }
        if len(listResult.Buckets) < len(buckets) {
            log.Printf("  WARNING: Expected %d buckets, found %d",
                len(buckets), len(listResult.Buckets))
            allOK = false
        }
    }
```

Lists all buckets and compares the count against expected. `*b.Name` dereferences the bucket name pointer. `len()` returns the length of a slice — like Java's `list.size()`.

```go
    if allOK {
        // success log
    } else {
        os.Exit(1)
    }
```

Exits with code 1 on failure. This is critical because Docker Compose uses exit code to determine if `service_completed_successfully` condition is met. A non-zero exit means dependent services won't start.

---

# 6. Service 2: Upload Service

**Purpose:** HTTP server serving a web upload form and handling file uploads to S3 with SQS notification.

**Java analogy:** A Spring Boot `@RestController` with a file upload endpoint, using S3Client and SqsClient.

## upload-service/main.go — Line by Line

### HTTP Server Setup

```go
func main() {
    // ... AWS client setup (same pattern as init-service) ...

    waitForResources()

    mux := http.NewServeMux()
    mux.HandleFunc("/", serveForm)
    mux.HandleFunc("/upload", handleUpload)
    mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
    })
```

`http.NewServeMux()` creates a URL router — Go's built-in equivalent of Spring's `DispatcherServlet` or Java's `@RequestMapping`. It maps URL patterns to handler functions.

- **`HandleFunc("/", serveForm)`**: Routes `GET /` to the `serveForm` function. Like `@GetMapping("/")`.
- **`HandleFunc("/upload", handleUpload)`**: Routes `/upload` to the upload handler. Like `@PostMapping("/upload")`.
- **The health endpoint** uses an **inline anonymous function** (closure). `map[string]string{"status": "ok"}` creates a literal map — like Java's `Map.of("status", "ok")`.

**Java equivalent:**
```java
@RestController
public class UploadController {
    @GetMapping("/")
    public String serveForm() { return "upload.html"; }

    @PostMapping("/upload")
    public ResponseEntity<Map<String, String>> handleUpload(@RequestParam MultipartFile file) { ... }

    @GetMapping("/health")
    public Map<String, String> health() { return Map.of("status", "ok"); }
}
```

Go's approach is more manual but gives you complete control. Spring Boot auto-configures everything; Go makes you wire it explicitly.

```go
    handler := recoveryMiddleware(mux)

    log.Println("Upload service listening on :8080")
    log.Fatal(http.ListenAndServe(":8080", handler))
}
```

- **`recoveryMiddleware(mux)`**: Wraps the router with panic recovery. Like Spring's `@ControllerAdvice` with `@ExceptionHandler`.
- **`http.ListenAndServe(":8080", handler)`**: Starts the HTTP server. This blocks forever (or until error). Like Tomcat's `start()` but in a single line.
- **`log.Fatal`**: If `ListenAndServe` returns (which means it failed), log the error and exit. It only returns on error; on success, it blocks forever.

### Recovery Middleware

```go
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
```

This is the **middleware pattern** in Go. The function takes a handler, wraps it with extra behavior, and returns a new handler.

- **`defer func() { ... }()`**: Defers an anonymous function that runs when the outer function returns. The `()` at the end immediately invokes the deferred function definition.
- **`recover()`**: Catches a panic (Go's version of an unrecoverable error/exception). Without this, a panic would crash the entire server. `recover()` only works inside a deferred function.
- **`next.ServeHTTP(w, r)`**: Calls the actual handler. If it panics, the deferred recover catches it.

**Java equivalent:**
```java
@ControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, String>> handleException(Exception e) {
        return ResponseEntity.status(500).body(Map.of("error", e.getMessage()));
    }
}
```

In Go, middleware is a function that wraps another function. In Java/Spring, it's annotations and AOP proxies. Go's approach is explicit and composable; Java's is declarative and magical.

### writeJSON Helper

```go
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
```

A centralized JSON response writer. Every response goes through this function to guarantee JSON output.

- **`data interface{}`**: Accepts any type. `interface{}` is Go's "any type" — like Java's `Object`. In Go 1.18+, you can use `any` as an alias.
- **`json.Marshal(data)`**: Serializes to JSON bytes. Like Jackson's `objectMapper.writeValueAsBytes(data)`.
- **`w.Header().Set(...)`**: Sets HTTP response headers. Must be called BEFORE `WriteHeader()`.
- **`w.WriteHeader(statusCode)`**: Sends the HTTP status code. Must be called BEFORE `Write()`.
- **`w.Write(body)`**: Writes the response body bytes.

**Critical order:** `Set headers → WriteHeader → Write body`. If you call `Write()` before `WriteHeader()`, Go automatically sends 200. If you call `WriteHeader()` twice, the second call is ignored. This is a common Go pitfall.

**Java equivalent:**
```java
private void writeJSON(HttpServletResponse resp, int status, Object data) throws IOException {
    String json = objectMapper.writeValueAsString(data);
    resp.setContentType("application/json");
    resp.setStatus(status);
    resp.getWriter().write(json);
}
```

### handleUpload — The Core Upload Logic

```go
func handleUpload(w http.ResponseWriter, r *http.Request) {
    log.Printf("[UPLOAD] %s /upload from %s", r.Method, r.RemoteAddr)

    if r.Method != http.MethodPost {
        writeJSON(w, http.StatusMethodNotAllowed,
            map[string]string{"error": "method not allowed, use POST"})
        return
    }
```

Go's `HandleFunc` doesn't filter by HTTP method (unlike Spring's `@PostMapping`). You must check `r.Method` manually. In Go 1.22+, you can use `mux.HandleFunc("POST /upload", handler)` to restrict methods.

```go
    if err := r.ParseMultipartForm(50 << 20); err != nil {
        log.Printf("[UPLOAD] ParseMultipartForm error: %v", err)
        writeJSON(w, http.StatusBadRequest,
            map[string]string{"error": "File too large or invalid form data: " + err.Error()})
        return
    }
```

- **`50 << 20`**: Bit shift operator. `50 << 20` = 50 × 2²⁰ = 50 × 1,048,576 = 52,428,800 bytes = 50MB. This is the max memory for parsing the multipart form. It's a Go idiom for expressing sizes in bytes.
- **`r.ParseMultipartForm`**: Parses the multipart request body. Like Spring's `@RequestParam("file") MultipartFile file` but manual.

**Java equivalent:**
```java
// Spring Boot handles this automatically with @RequestParam MultipartFile
// Or manually:
Part filePart = request.getPart("file");
if (filePart.getSize() > 50 * 1024 * 1024) { throw new FileTooLargeException(); }
```

```go
    file, header, err := r.FormFile("file")
    if err != nil {
        writeJSON(w, http.StatusBadRequest,
            map[string]string{"error": "No file provided: " + err.Error()})
        return
    }
    defer file.Close()
```

`r.FormFile("file")` returns three values:
1. `file` — an `io.ReadCloser` (the file content stream)
2. `header` — a `*multipart.FileHeader` (filename, size, content-type)
3. `err` — error if no file found

`defer file.Close()` ensures the file stream is closed when the function returns, even if an error occurs later.

```go
    documentID := uuid.New().String()
    ext := strings.ToLower(filepath.Ext(header.Filename))
    s3Key := fmt.Sprintf("%s/%s%s", documentID, documentID, ext)
    bucket := os.Getenv("S3_UPLOAD_BUCKET")
```

Generates a unique document ID and constructs the S3 key. Example: for a file named `report.pdf`, this creates:
- `documentID` = `"a1b2c3d4-e5f6-7890-abcd-ef1234567890"`
- `ext` = `".pdf"`
- `s3Key` = `"a1b2c3d4-.../a1b2c3d4-....pdf"`

```go
    var buf bytes.Buffer
    if _, err := io.Copy(&buf, file); err != nil {
        writeJSON(w, http.StatusInternalServerError,
            map[string]string{"error": "Failed to read uploaded file"})
        return
    }
```

Buffers the entire file into memory. `io.Copy(&buf, file)` reads from `file` and writes to `buf` until EOF. This is necessary because the S3 SDK may need to read the body multiple times (for retries), and a stream can only be read once.

**Java equivalent:**
```java
byte[] fileBytes = filePart.getInputStream().readAllBytes();
```

```go
    _, err = s3Client.PutObject(context.TODO(), &s3.PutObjectInput{
        Bucket:      aws.String(bucket),
        Key:         aws.String(s3Key),
        Body:        bytes.NewReader(buf.Bytes()),
        ContentType: aws.String(contentType),
    })
```

Uploads to S3. `bytes.NewReader(buf.Bytes())` creates an `io.Reader` from the byte buffer — the S3 SDK reads from this.

```go
    msg := SQSMessage{
        Type:        "file_uploaded",
        DocumentID:  documentID,
        Filename:    header.Filename,
        ContentType: contentType,
        S3Key:       s3Key,
        Timestamp:   time.Now().UTC().Format(time.RFC3339),
    }

    msgBytes, err := json.Marshal(msg)
```

Creates the SQS message struct and serializes to JSON. `time.Now().UTC().Format(time.RFC3339)` produces an ISO 8601 timestamp like `"2024-01-15T10:30:00Z"`.

**Java equivalent:**
```java
SQSMessage msg = new SQSMessage("file_uploaded", documentId, ...);
String json = objectMapper.writeValueAsString(msg);
sqsClient.sendMessage(SendMessageRequest.builder()
    .queueUrl(queueUrl)
    .messageBody(json)
    .build());
```

### waitForResources

```go
func waitForResources() {
    bucket := os.Getenv("S3_UPLOAD_BUCKET")
    queueURL := os.Getenv("SQS_QUEUE_URL")

    for i := 0; i < 60; i++ {
        _, s3Err := s3Client.HeadBucket(context.TODO(), &s3.HeadBucketInput{
            Bucket: aws.String(bucket),
        })
        _, sqsErr := sqsClient.GetQueueAttributes(context.TODO(), &sqs.GetQueueAttributesInput{
            QueueUrl:       aws.String(queueURL),
            AttributeNames: []sqstypes.QueueAttributeName{sqstypes.QueueAttributeNameAll},
        })

        if s3Err == nil && sqsErr == nil {
            log.Println("All resources ready!")
            return
        }
        time.Sleep(2 * time.Second)
    }
    log.Println("WARNING: Timed out waiting for resources, starting anyway...")
}
```

Polls every 2 seconds up to 60 times (2 minutes) waiting for the init service to create the resources. This is a safety net in case Docker's `depends_on` timing isn't perfect.

`[]sqstypes.QueueAttributeName{sqstypes.QueueAttributeNameAll}` is a slice containing one enum value. In Java: `List.of(QueueAttributeName.ALL)`.

---

# 7. Service 3: Text Extract Service

**Purpose:** Long-running worker that polls the `file-processing` SQS queue, determines file types, extracts text using CLI tools, and routes images to the OCR service.

## The Polling Loop Pattern

```go
func pollMessages() {
    queueURL := os.Getenv("SQS_FILE_QUEUE_URL")

    for {      // Infinite loop — this service runs forever
        result, err := sqsClient.ReceiveMessage(context.TODO(), &sqs.ReceiveMessageInput{
            QueueUrl:            aws.String(queueURL),
            MaxNumberOfMessages: 1,           // Process one at a time
            WaitTimeSeconds:     20,          // Long polling: block up to 20 seconds
            VisibilityTimeout:   300,         // Hide message for 5 minutes while processing
        })
        if err != nil {
            log.Printf("Error receiving messages: %v", err)
            time.Sleep(5 * time.Second)       // Back off on errors
            continue                           // Skip to next iteration
        }

        for _, msg := range result.Messages {
            processMessage(msg, queueURL)
        }
    }
}
```

This is the **consumer loop pattern** — the Go equivalent of a JMS `MessageListener` or Spring's `@SqsListener`.

**Key parameters:**
- **`MaxNumberOfMessages: 1`**: Process one message at a time. Simple but safe. For higher throughput, increase this and process in goroutines.
- **`WaitTimeSeconds: 20`**: **Long polling**. The call blocks for up to 20 seconds waiting for a message. Without this, you'd burn CPU constantly making empty requests (short polling).
- **`VisibilityTimeout: 300`**: After receiving a message, it becomes invisible to other consumers for 5 minutes. If we don't delete it within that time (meaning processing failed), it reappears for another consumer to retry.
- **`continue`**: Skips to the next loop iteration — like Java's `continue`.

**Java equivalent (Spring Cloud AWS):**
```java
@SqsListener("file-processing")
public void handleMessage(@Payload FileUploadedMessage msg) {
    processDocument(msg);
}
```

Spring handles the polling loop, deserialization, visibility management, and deletion automatically. Go makes you write it all explicitly.

### Message Processing

```go
func processMessage(msg sqstypes.Message, queueURL string) {
    var fileMsg FileUploadedMessage
    if err := json.Unmarshal([]byte(*msg.Body), &fileMsg); err != nil {
        log.Printf("Failed to parse message: %v", err)
        deleteMessage(queueURL, msg.ReceiptHandle)
        return
    }
```

- **`*msg.Body`**: Dereferences the pointer. `msg.Body` is `*string`; `*msg.Body` gives us the `string` value.
- **`json.Unmarshal([]byte(...), &fileMsg)`**: Deserializes JSON into the struct. The `&` passes a pointer so `Unmarshal` can modify `fileMsg`. Like Jackson's `objectMapper.readValue(json, FileUploadedMessage.class)`.
- **Always delete invalid messages**: If we can't parse a message, delete it anyway to prevent infinite reprocessing (poison pill pattern).

```go
    err := processDocument(fileMsg)
    if err != nil {
        log.Printf("Error processing document %s: %v", fileMsg.DocumentID, err)
    }

    deleteMessage(queueURL, msg.ReceiptHandle)   // Always delete, even on error
}
```

Messages are deleted after processing regardless of success/failure. In production, you might want a dead-letter queue for failures.

### File Type Routing

```go
func processDocument(msg FileUploadedMessage) error {
    tmpDir, err := os.MkdirTemp("", "extract-"+msg.DocumentID)
    if err != nil {
        return fmt.Errorf("failed to create temp dir: %w", err)
    }
    defer os.RemoveAll(tmpDir)
```

- **`os.MkdirTemp("", "extract-...")`**: Creates a temporary directory. The first arg `""` means use the system default temp dir. Like Java's `Files.createTempDirectory("extract-...")`.
- **`defer os.RemoveAll(tmpDir)`**: Automatically clean up the temp directory when the function returns. This is crucial — without it, temp files would accumulate forever.
- **`fmt.Errorf("... : %w", err)`**: Creates a new error that wraps the original. The `%w` verb enables error unwrapping (like Java's `new RuntimeException("msg", cause)`).

```go
    fileType := categorizeFile(ext, msg.ContentType)

    switch fileType {
    case "pdf":
        return processPDF(msg, localPath, tmpDir)
    case "word":
        return processWord(msg, localPath, tmpDir)
    case "rtf":
        return processRTF(msg, localPath, tmpDir)
    case "image":
        return processImage(msg)
    default:
        return fmt.Errorf("unsupported file type: %s", ext)
    }
}
```

Go's `switch` doesn't need `break` — each case automatically breaks. This is the opposite of Java where you must write `break` explicitly. To fall through in Go, you'd write `fallthrough` (rarely used).

### PDF Processing — The Most Complex Handler

```go
func processPDF(msg FileUploadedMessage, localPath, tmpDir string) error {
    // Step 1: Extract text
    textPath := filepath.Join(tmpDir, "extracted.txt")
    cmd := exec.Command("pdftotext", "-layout", localPath, textPath)
    if output, err := cmd.CombinedOutput(); err != nil {
        return fmt.Errorf("pdftotext failed: %w", err)
    }
```

- **`exec.Command("pdftotext", ...)`**: Creates an external process. Like Java's `new ProcessBuilder("pdftotext", ...)`. Each argument is a separate string, not a shell command.
- **`cmd.CombinedOutput()`**: Runs the command and captures stdout+stderr. Returns the output as `[]byte` and an error. Like Java's `process.waitFor()` + reading stdout.
- **`pdftotext -layout`**: Extracts text from PDF preserving layout. This is a Poppler utility installed in the Docker image.

```go
    // Step 2: Extract images from PDF
    imageDir := filepath.Join(tmpDir, "images")
    os.MkdirAll(imageDir, 0755)
    imagePrefix := filepath.Join(imageDir, "img")

    cmd = exec.Command("pdfimages", "-png", localPath, imagePrefix)
    if output, err := cmd.CombinedOutput(); err != nil {
        return nil   // Not fatal — PDF may have no images
    }
```

- **`os.MkdirAll(imageDir, 0755)`**: Creates directory and all parents. `0755` is Unix permissions (rwxr-xr-x). Like Java's `Files.createDirectories(path)`.
- **`pdfimages -png`**: Extracts embedded images from PDF as PNG files. Creates files like `img-000.png`, `img-001.png`, etc.
- Returns `nil` (no error) if pdfimages fails — a PDF might simply have no images.

```go
    imageFiles, err := filepath.Glob(filepath.Join(imageDir, "img-*.png"))
    if err != nil || len(imageFiles) == 0 {
        return nil
    }
```

`filepath.Glob` finds files matching a pattern — like Java's `PathMatcher` or shell globbing.

```go
    for i, imgPath := range imageFiles {
        imgKey := fmt.Sprintf("%s/image-%03d.png", msg.DocumentID, i+1)
        if err := uploadToS3(os.Getenv("S3_TMP_BUCKET"), imgKey, imgPath); err != nil {
            continue   // Skip this image, try the next
        }

        ocrMsg := OCRMessage{
            Type:         "ocr_needed",
            DocumentID:   msg.DocumentID,
            DocumentType: "pdf_image",
            S3Bucket:     os.Getenv("S3_TMP_BUCKET"),
            S3Key:        imgKey,
            ImageIndex:   i + 1,
            Timestamp:    time.Now().UTC().Format(time.RFC3339),
        }
        sendOCRMessage(ocrMsg)
    }
```

For each extracted image:
1. Upload it to the `tmp-files` S3 bucket
2. Send an `ocr_needed` message to the OCR queue

`%03d` formats as zero-padded 3 digits: `001`, `002`, etc. Like Java's `String.format("%03d", i)`.

### S3 Helper Functions

```go
func downloadFromS3(bucket, key, localPath string) error {
    result, err := s3Client.GetObject(context.TODO(), &s3.GetObjectInput{
        Bucket: aws.String(bucket),
        Key:    aws.String(key),
    })
    if err != nil {
        return err
    }
    defer result.Body.Close()

    file, err := os.Create(localPath)
    if err != nil {
        return err
    }
    defer file.Close()

    _, err = io.Copy(file, result.Body)
    return err
}
```

Downloads from S3 to a local file. `io.Copy(dst, src)` streams data from `result.Body` (the S3 response stream) to `file` (the local file) without buffering the entire thing in memory. Like Java's `InputStream.transferTo(OutputStream)`.

Two `defer` statements: `result.Body.Close()` and `file.Close()`. They execute in reverse order (LIFO): file closes first, then the S3 response body.

```go
func uploadToS3(bucket, key, localPath string) error {
    data, err := os.ReadFile(localPath)
    if err != nil {
        return err
    }

    _, err = s3Client.PutObject(context.TODO(), &s3.PutObjectInput{
        Bucket:      aws.String(bucket),
        Key:         aws.String(key),
        Body:        bytes.NewReader(data),
        ContentType: aws.String("text/plain"),
    })
    return err
}
```

`os.ReadFile(localPath)` reads the entire file into a `[]byte`. Like Java's `Files.readAllBytes(path)`. Then uploads via `PutObject`.

### SQS Helper Functions

```go
func sendOCRMessage(msg OCRMessage) error {
    msgBytes, err := json.Marshal(msg)
    if err != nil {
        return err
    }

    queueURL := os.Getenv("SQS_OCR_QUEUE_URL")
    _, err = sqsClient.SendMessage(context.TODO(), &sqs.SendMessageInput{
        QueueUrl:    aws.String(queueURL),
        MessageBody: aws.String(string(msgBytes)),
    })
    return err
}
```

Serializes the struct to JSON and sends it. `string(msgBytes)` converts `[]byte` to `string` — a type conversion, not a method call.

```go
func deleteMessage(queueURL string, receiptHandle *string) {
    _, err := sqsClient.DeleteMessage(context.TODO(), &sqs.DeleteMessageInput{
        QueueUrl:      aws.String(queueURL),
        ReceiptHandle: receiptHandle,
    })
    if err != nil {
        log.Printf("Failed to delete message: %v", err)
    }
}
```

Deletes a processed message from the queue. The `receiptHandle` is a unique token for the specific receipt of the message — SQS uses it to identify which consumer's copy to delete.

---

# 8. Service 4: OCR Service

**Purpose:** Receives `ocr_needed` messages, downloads images from S3, runs Tesseract OCR, saves the extracted text, and sends `ocr_complete` notifications.

The OCR service follows the same polling pattern as the text extract service. The unique parts are the OCR processing functions.

### ocrImage — Single Image OCR

```go
func ocrImage(msg OCRMessage, inputPath, tmpDir string) error {
    outputBase := filepath.Join(tmpDir, "ocr-output")
    cmd := exec.Command("tesseract", inputPath, outputBase, "-l", "eng", "--psm", "1")
    if output, err := cmd.CombinedOutput(); err != nil {
        // Try with different PSM mode
        cmd = exec.Command("tesseract", inputPath, outputBase, "-l", "eng", "--psm", "3")
        if output2, err2 := cmd.CombinedOutput(); err2 != nil {
            return fmt.Errorf("tesseract failed: %s - %w", string(output2), err2)
        }
    }
```

- **`tesseract inputPath outputBase -l eng --psm 1`**: Runs Tesseract OCR.
  - `inputPath`: The image file to OCR
  - `outputBase`: Output filename without extension (Tesseract adds `.txt`)
  - `-l eng`: Use English language model
  - `--psm 1`: Page Segmentation Mode 1 = "Automatic with OSD" (orientation and script detection)
- **Fallback to `--psm 3`**: If mode 1 fails, try mode 3 = "Fully automatic" (simpler algorithm). This is defensive coding for different image types.

```go
    var outputKey string
    if msg.ImageIndex > 0 {
        outputKey = fmt.Sprintf("%s-image-%03d.txt", msg.DocumentID, msg.ImageIndex)
    } else {
        outputKey = fmt.Sprintf("%s.txt", msg.DocumentID)
    }
```

Names the output file based on whether it's a standalone image upload (just `{docId}.txt`) or an image extracted from a PDF (`{docId}-image-001.txt`).

### ocrPDF — Multi-Page PDF OCR

```go
func ocrPDF(msg OCRMessage, inputPath, tmpDir string) error {
    imagePrefix := filepath.Join(tmpDir, "page")
    cmd := exec.Command("pdftoppm", "-png", "-r", "300", inputPath, imagePrefix)
```

- **`pdftoppm -png -r 300`**: Converts PDF pages to PNG images at 300 DPI. Higher DPI = better OCR accuracy but larger files. 300 DPI is the standard for OCR.
- Creates files: `page-01.png`, `page-02.png`, etc.

```go
    var allText bytes.Buffer
    for i, pagePath := range pageImages {
        outputBase := filepath.Join(tmpDir, fmt.Sprintf("ocr-page-%03d", i+1))
        cmd := exec.Command("tesseract", pagePath, outputBase, "-l", "eng", "--psm", "1")
        if output, err := cmd.CombinedOutput(); err != nil {
            continue    // Skip failed pages, continue with the rest
        }

        textData, err := os.ReadFile(outputBase + ".txt")
        if err != nil {
            continue
        }

        allText.WriteString(fmt.Sprintf("--- Page %d ---\n", i+1))
        allText.Write(textData)
        allText.WriteString("\n\n")
    }
```

Processes each page individually, concatenating results into a `bytes.Buffer` (like Java's `StringBuilder` but for bytes). Failed pages are skipped with `continue` rather than failing the whole document.

---

# 9. Coding Decisions: Pros and Cons

## 9.1 Decision: Single-threaded Message Processing

**What:** Each service processes one SQS message at a time in a sequential loop.

**Pro:**
- Simple to reason about — no race conditions, no shared state
- No mutex locks needed
- Easy to debug and log
- Each message gets the full CPU and memory

**Con:**
- Throughput limited to one message at a time
- Long-running OCR blocks the next message
- Can't utilize multiple CPU cores

**Alternative (concurrent processing):**
```go
for _, msg := range result.Messages {
    go processMessage(msg, queueURL)  // Process in a goroutine
}
```

**Java comparison:** In Java/Spring, you'd typically use `@SqsListener` with `maxConcurrentMessages=10` and a thread pool. Spring handles the concurrency for you. In Go, you'd manually manage goroutines.

## 9.2 Decision: Package-Level Global Variables for AWS Clients

```go
var (
    s3Client  *s3.Client
    sqsClient *sqs.Client
)
```

**Pro:**
- Simple — any function can access the clients
- No dependency injection framework needed
- Easy to understand for beginners

**Con:**
- Global mutable state (though only set once at startup)
- Hard to unit test (can't inject mocks easily)
- Doesn't scale to larger applications

**Alternative (dependency injection):**
```go
type App struct {
    s3Client  *s3.Client
    sqsClient *sqs.Client
}

func (a *App) handleUpload(w http.ResponseWriter, r *http.Request) {
    // Use a.s3Client instead of global
}
```

**Java comparison:** Java developers would use Spring's `@Autowired` or constructor injection. Go doesn't have a DI framework — you pass dependencies explicitly through struct fields or function parameters. Libraries like `wire` (Google) or `fx` (Uber) provide compile-time DI.

## 9.3 Decision: Environment Variables for Configuration

```go
endpoint := os.Getenv("LOCALSTACK_ENDPOINT")
bucket := os.Getenv("S3_UPLOAD_BUCKET")
```

**Pro:**
- 12-factor app compliant
- Docker-native — environment variables are the standard way to configure containers
- No config file parsing code needed

**Con:**
- No type safety (everything is a string)
- No validation at startup — typos discovered at runtime
- No defaults visible in one place

**Alternative:** Use a config struct with validation:
```go
type Config struct {
    Endpoint string `env:"LOCALSTACK_ENDPOINT" envDefault:"http://localstack:4566"`
    Bucket   string `env:"S3_UPLOAD_BUCKET" required:"true"`
}
```

**Java comparison:** Spring Boot's `@ConfigurationProperties` with `@Value` annotations provide type-safe, validated configuration with defaults. Go's approach is more manual but requires no framework.

## 9.4 Decision: Shelling Out to CLI Tools (pdftotext, tesseract)

```go
cmd := exec.Command("pdftotext", "-layout", localPath, textPath)
```

**Pro:**
- Mature, battle-tested tools (Poppler, Tesseract)
- No CGO (C binding) complexity — pure Go binary + CLI tools
- Easy to swap tools (e.g., replace `pdftotext` with `pdfplumber`)
- CLI tools are the same regardless of host language

**Con:**
- Process spawning overhead per file
- Harder to handle errors (exit codes + stderr parsing)
- Must install tools in Docker image (increases image size)
- No fine-grained control over tool behavior

**Alternative:** Use pure Go libraries:
```go
import "github.com/ledongthuc/pdf"  // Pure Go PDF reader
```

**Java comparison:** Java would use Apache PDFBox (pure Java), Apache Tika (Java), or Tess4J (JNI wrapper for Tesseract). Go's ecosystem has fewer pure-Go PDF/OCR libraries, making CLI tools the pragmatic choice.

## 9.5 Decision: `error` Return Values vs Custom Error Types

```go
return fmt.Errorf("pdftotext failed: %w", err)
```

**Pro:**
- Simple, consistent pattern across entire codebase
- Error wrapping with `%w` preserves the chain
- Readable error messages

**Con:**
- No distinction between error types (retriable vs permanent)
- Caller can't easily handle specific errors differently
- No stack traces

**Alternative:** Custom error types:
```go
type RetryableError struct {
    Message string
    Cause   error
}

func (e *RetryableError) Error() string { return e.Message }
func (e *RetryableError) Unwrap() error { return e.Cause }
```

**Java comparison:** Java's exception hierarchy (`IOException`, `RuntimeException`, etc.) with `try-catch` blocks provides automatic stack traces and typed error handling. Go's approach is simpler but less informative.

## 9.6 Decision: Embedded HTML in Go Source

```go
html := `<!DOCTYPE html>
<html lang="en">
...
</html>`
```

**Pro:**
- No template engine dependency
- Single-file deployment — the binary contains everything
- Raw string literal (backticks) preserves HTML exactly

**Con:**
- Mixing concerns (Go code + HTML + CSS + JavaScript)
- No syntax highlighting or IDE support for embedded HTML
- Changes require recompilation
- Hard to maintain as the UI grows

**Alternative:** Use Go's `html/template` package or embed files:
```go
//go:embed templates/upload.html
var uploadHTML string
```

**Java comparison:** Java typically uses separate template files (Thymeleaf, JSP, or separate React frontend). Go's `embed` directive (Go 1.16+) can bundle files into the binary while keeping them separate in source.

---

# 10. Go vs Java Comparison Summary

| Aspect | Go | Java | Winner For This Project |
|--------|-----|------|------------------------|
| **Startup time** | ~10ms | ~2-5s (Spring Boot) | Go — microservices restart fast |
| **Memory usage** | ~10-15MB | ~150-300MB | Go — critical for many containers |
| **Docker image** | ~15-20MB | ~200-300MB | Go — faster pulls, less storage |
| **Compilation** | ~2s | ~10-30s (Maven) | Go — faster feedback loop |
| **Error handling** | Explicit (`if err != nil`) | Exceptions (`try-catch`) | Java — less verbose |
| **HTTP server** | Built-in `net/http` | Spring Boot (framework) | Tie — Go is simpler, Spring is richer |
| **JSON handling** | Struct tags + `encoding/json` | Jackson annotations | Tie — similar ergonomics |
| **AWS SDK** | Verbose, pointer-heavy | Cleaner builder pattern | Java — better API design |
| **Dependency injection** | Manual or third-party | Spring `@Autowired` | Java — DI is effortless |
| **Concurrency** | Goroutines (lightweight) | Virtual threads (Java 21+) | Tie — both excellent |
| **Testing** | `go test` built-in | JUnit + Mockito + Spring Test | Java — richer testing ecosystem |
| **Learning curve** | Small language, few concepts | Large ecosystem, many patterns | Go — faster to learn |
| **IDE support** | VS Code + gopls | IntelliJ (excellent) | Java — best-in-class IDE |
| **Binary distribution** | Single static binary | JAR + JVM | Go — zero dependencies |
| **Ecosystem maturity** | Growing | Very mature | Java — broader library choice |

## When to Use Go (Like This Project)

- Microservices with many containers (memory and image size matter)
- CLI tools and system utilities
- High-concurrency network services
- Projects where fast startup/shutdown matters (serverless, container orchestration)
- Teams that want simplicity over framework magic

## When to Use Java (Instead)

- Large enterprise applications with complex business logic
- Projects relying on rich framework ecosystem (Spring, Hibernate, etc.)
- Teams already experienced with Java
- Applications needing mature monitoring/observability (Micrometer, Actuator)
- Projects where compile-time DI and AOP are essential

---

# 11. Running the Application

```bash
# Clone and start
cd ocr-service
docker-compose up --build

# Watch logs
docker-compose logs -f

# Open browser
open http://localhost:8080

# Check S3 buckets
aws --endpoint-url=http://localhost:4566 s3 ls
aws --endpoint-url=http://localhost:4566 s3 ls s3://extracted-text/ --recursive

# Check SQS queues
aws --endpoint-url=http://localhost:4566 sqs list-queues

# Retrieve extracted text
aws --endpoint-url=http://localhost:4566 s3 cp s3://extracted-text/{doc-id}.txt -

# Stop everything
docker-compose down -v
```

## Processing Flow When You Upload a PDF

1. Browser POSTs file to upload-service (`:8080/upload`)
2. Upload service saves to `s3://uploads/{docId}/{docId}.pdf`
3. Upload service sends `{"type":"file_uploaded",...}` to SQS `file-processing`
4. Text-extract service receives message, downloads PDF
5. Runs `pdftotext` → saves text to `s3://extracted-text/{docId}.txt`
6. Runs `pdfimages` → extracts embedded images
7. For each image: uploads to `s3://tmp-files/{docId}/image-001.png`
8. Sends `{"type":"ocr_needed",...}` to SQS `ocr-processing` for each image
9. OCR service receives each message, downloads image
10. Runs `tesseract` → saves OCR text to `s3://tmp-extracted-text/{docId}-image-001.txt`
11. Sends `{"type":"ocr_complete",...}` to SQS `ocr-complete`

---
