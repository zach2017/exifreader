# OCR Lambda Client — Java 21 CLI

A command-line client for invoking the OCR Lambda functions (`handler.py`, `pdf_handler.py`, `pdf_ocr_handler.py`) via the AWS SDK for Java v2.

Built with Java 21 features: sealed interfaces, records, pattern matching switch expressions, and text blocks.

---

## Prerequisites

- **Java 21+** (verify with `java --version`)
- **Maven 3.9+** (verify with `mvn --version`)
- **AWS credentials** configured — via `~/.aws/credentials`, environment variables, IAM role, or SSO
- **Deployed Lambda functions** — the three Python handlers deployed to AWS Lambda

## Build

```bash
# Compile, test, and build fat JAR
mvn clean package

# Skip tests if needed
mvn clean package -DskipTests

# The fat JAR is at target/ocr-client-1.0.0.jar
```

Create an alias for convenience:

```bash
alias ocr-client='java -jar target/ocr-client-1.0.0.jar'
```

## Quick Start

```bash
# Auto-detect file type (image → Tesseract, PDF → text extraction)
ocr-client scan invoice.pdf

# OCR a scanned PDF (render pages to images, then Tesseract)
ocr-client pdf-ocr scanned-document.pdf

# OCR an image
ocr-client image receipt.jpg

# Extract text from a digital PDF
ocr-client pdf-extract report.pdf
```

## Commands

### `scan` — Auto-detect and process

Inspects the file extension and routes to the appropriate Lambda:

```bash
# Digital PDF → pdf_handler.py
ocr-client scan report.pdf

# Scanned PDF → pdf_ocr_handler.py (with --force-ocr)
ocr-client scan scanned.pdf --force-ocr --dpi 600

# Image → handler.py
ocr-client scan photo.png
```

### `image` — Image OCR

Calls `handler.py` → Tesseract OCR:

```bash
ocr-client image screenshot.png
ocr-client image receipt.jpg --output json
ocr-client image whiteboard.tiff --save-to notes.txt
```

### `pdf-extract` — Digital PDF text extraction

Calls `pdf_handler.py` → PyMuPDF text layer extraction:

```bash
ocr-client pdf-extract annual-report.pdf
ocr-client pdf-extract contract.pdf --output text --save-to contract.txt
```

### `pdf-ocr` — Scanned PDF OCR pipeline

Calls `pdf_ocr_handler.py` → PyMuPDF render + Tesseract per page:

```bash
ocr-client pdf-ocr old-scan.pdf
ocr-client pdf-ocr fax.pdf --dpi 600 --output summary
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-o, --output` | Output format: `summary`, `text`, `json` | `summary` |
| `-s, --save-to FILE` | Save extracted text to a file | — |
| `-r, --region` | AWS region | `us-east-1` |
| `--image-fn` | Image OCR Lambda function name | `ocr-image` |
| `--pdf-fn` | PDF extract Lambda function name | `ocr-pdf` |
| `--pdf-ocr-fn` | PDF OCR Lambda function name | `ocr-pdf-ocr` |
| `--dpi` | Render DPI for PDF OCR | `300` |
| `--max-size` | Max input file size in MB | `10` |
| `--force-ocr` | Force OCR pipeline for PDFs (scan command) | `false` |

## Environment Variables

All Lambda function names and the AWS region can be configured via environment variables:

```bash
export OCR_AWS_REGION=eu-west-1
export OCR_IMAGE_FUNCTION=my-image-ocr
export OCR_PDF_FUNCTION=my-pdf-extract
export OCR_PDF_OCR_FUNCTION=my-pdf-ocr
```

## Output Formats

### `--output summary` (default)

Human-readable with stats and timing:

```
────────────────────────────────────────────────────────────
  PDF OCR Pipeline Result
────────────────────────────────────────────────────────────
  File:       scan.pdf
  Pages:      3
  DPI:        300
  Words:      1,247
  Characters: 7,891
  PDF size:   1.2 MB

  Timing breakdown:
    Total pipeline:    4,520 ms
    Image rendering:   1,200 ms (avg 400 ms/page)
    OCR processing:    3,100 ms (avg 1033 ms/page)
────────────────────────────────────────────────────────────

── Page 1 (412 words | render 380 ms | OCR 1050 ms) ──
[extracted text here...]
```

### `--output text`

Raw extracted text only (ideal for piping):

```bash
ocr-client scan report.pdf --output text | wc -w
ocr-client image receipt.jpg --output text | grep "Total"
```

### `--output json`

Full Lambda response as pretty-printed JSON:

```bash
ocr-client scan doc.pdf --output json | jq '.page_count'
```

## Project Structure

```
ocr-client/
├── pom.xml                               # Maven build with shade plugin
├── src/
│   ├── main/java/com/ocr/
│   │   ├── client/
│   │   │   ├── OcrCli.java              # picocli CLI with subcommands
│   │   │   └── LambdaInvoker.java       # AWS Lambda invocation service
│   │   ├── model/
│   │   │   ├── OcrRequest.java          # Sealed interface + request records
│   │   │   └── OcrResponse.java         # Response records with @SerializedName
│   │   └── util/
│   │       ├── FileUtils.java           # File I/O, base64, type detection
│   │       └── OutputFormatter.java     # JSON / text / summary formatting
│   └── test/java/com/ocr/
│       ├── FileUtilsTest.java
│       ├── ModelAndPayloadTest.java
│       └── OutputFormatterTest.java
```

## Java 21 Features Used

| Feature | Where |
|---------|-------|
| **Sealed interfaces** | `OcrRequest` — exhaustive type hierarchy for the 3 request kinds |
| **Records** | All request/response models — immutable data carriers with auto-generated methods |
| **Pattern matching switch** | `LambdaInvoker.invokeRaw()`, `ScanCommand.call()` — exhaustive dispatch |
| **Switch expressions** | Throughout — concise control flow returning values |
| **Text blocks** | Test JSON literals — multi-line strings with `"""` |
| **`String.formatted()`** | All string formatting — instance method alternative to `String.format()` |
| **`var` local inference** | Used throughout for readability |

## Running Tests

```bash
mvn test
```

## Troubleshooting

**"No credential provider" error**: Ensure AWS credentials are configured. The client uses `DefaultCredentialsProvider` which checks (in order): environment variables, system properties, `~/.aws/credentials`, EC2/ECS instance roles, SSO.

**"Function not found" error**: Verify the Lambda function names match your deployment. Use `--image-fn`, `--pdf-fn`, `--pdf-ocr-fn` flags or environment variables to override.

**Timeout on large PDFs**: Lambda has a 15-minute max timeout. For very large PDFs via `pdf-ocr`, consider reducing DPI (`--dpi 150`) or splitting the PDF first.
