# Go for Java Developers: OCR Lambda Function — A Complete Line-by-Line Tutorial

> **Audience**: Java developers new to Go (Golang)
> **Project**: An AWS Lambda function written in Go that performs OCR on images using Tesseract, uploads results to S3, and sends notifications to SQS.

---

## Table of Contents

1. [Go vs Java — Key Differences at a Glance](#1-go-vs-java--key-differences-at-a-glance)
2. [Understanding go.mod — Go's Build File (Like pom.xml)](#2-understanding-gomod--gos-build-file-like-pomxml)
3. [main.go — The Lambda Function Line by Line](#3-maingo--the-lambda-function-line-by-line)
   - [Package Declaration & Imports](#31-package-declaration--imports)
   - [Constants](#32-constants)
   - [Struct Types (Like Java Classes)](#33-struct-types-like-java-classes)
   - [Interfaces (Implicit, Not Explicit)](#34-interfaces-implicit-not-explicit)
   - [Function Variables (Mockable Functions)](#35-function-variables-mockable-functions)
   - [The Tesseract OCR Function](#36-the-tesseract-ocr-function)
   - [The Processor Struct & Constructor](#37-the-processor-struct--constructor)
   - [AWS Configuration](#38-aws-configuration)
   - [Core Business Logic — processImage](#39-core-business-logic--processimage)
   - [S3 Download & Upload Methods](#310-s3-download--upload-methods)
   - [SQS Message Sending](#311-sqs-message-sending)
   - [Helper Functions](#312-helper-functions)
   - [Lambda Entry Point & main()](#313-lambda-entry-point--main)
4. [main_test.go — Unit Tests Line by Line](#4-main_testgo--unit-tests-line-by-line)
   - [Mock Implementations](#41-mock-implementations)
   - [Table-Driven Tests](#42-table-driven-tests)
   - [Testing With Mocked Dependencies](#43-testing-with-mocked-dependencies)
5. [Building & Running](#5-building--running)
6. [Reference Links](#6-reference-links)

---

## 1. Go vs Java — Key Differences at a Glance

Before diving into code, here are the most important differences you'll encounter:

| Concept | Java | Go |
|---------|------|-----|
| **File structure** | One public class per file | Multiple types/functions per file; all files in a directory share a package |
| **Entry point** | `public static void main(String[] args)` | `func main()` in `package main` |
| **Classes** | `class Foo { }` | `type Foo struct { }` — Go has no classes, only structs with methods |
| **Inheritance** | `extends`, `implements` | Composition via embedding; interfaces are satisfied implicitly |
| **Interfaces** | Explicit: `class Foo implements Bar` | Implicit: if a type has the right methods, it satisfies the interface automatically |
| **Visibility** | `public`/`private`/`protected` | Uppercase = exported (public), lowercase = unexported (package-private) |
| **Exceptions** | `try/catch/throw` | Multiple return values: `result, err := doSomething()` |
| **Null** | `null` / `NullPointerException` | `nil` — but only for pointers, interfaces, slices, maps, channels, and functions |
| **Generics** | Yes (since Java 5) | Yes (since Go 1.18), but used sparingly |
| **Packages** | `import com.example.foo;` | `import "github.com/user/repo/package"` |
| **Build tool** | Maven/Gradle | `go build`, `go test`, `go mod` |
| **Dependency file** | `pom.xml` / `build.gradle` | `go.mod` |
| **Getters/Setters** | Conventional | Not idiomatic — use exported fields directly |
| **Constructors** | `new Foo()` | Factory functions: `func NewFoo() *Foo { }` |
| **Pointers** | References (hidden) | Explicit: `*Foo` (pointer to Foo), `&foo` (address of foo) |
| **Unused imports** | Warning | Compile error — Go is strict |

> **Reference**: [Go for Java Programmers — Go Wiki](https://go.dev/wiki/FromJavaToComeToGo)

---

## 2. Understanding go.mod — Go's Build File (Like pom.xml)

The `go.mod` file is Go's equivalent of Maven's `pom.xml` or Gradle's `build.gradle`. It declares the module name and all dependencies.

```go
module ocr-lambda          // ← Module name (like Maven groupId + artifactId)

go 1.22                    // ← Minimum Go version required (like <java.version>)
```

**`module ocr-lambda`** — This is the module path. In open-source projects, this would typically be `github.com/username/ocr-lambda`. For private/local projects, any name works. Every `import` within this project is relative to this module name.

> **Java equivalent**: This is like the `<groupId>com.example</groupId><artifactId>ocr-lambda</artifactId>` in your `pom.xml`.

```go
require (
    github.com/aws/aws-lambda-go v1.47.0          // Lambda runtime SDK
    github.com/aws/aws-sdk-go-v2 v1.32.6          // AWS SDK core
    github.com/aws/aws-sdk-go-v2/config v1.28.6   // AWS config loading
    github.com/aws/aws-sdk-go-v2/credentials v1.17.47  // Static credentials
    github.com/aws/aws-sdk-go-v2/service/s3 v1.71.1    // S3 client
    github.com/aws/aws-sdk-go-v2/service/sqs v1.37.3   // SQS client
)
```

**`require (...)`** — These are your direct dependencies, like `<dependency>` blocks in Maven. Each line is `module-path version`.

> **Java equivalent**:
> ```xml
> <dependency>
>     <groupId>com.amazonaws</groupId>
>     <artifactId>aws-lambda-java-core</artifactId>
>     <version>1.2.3</version>
> </dependency>
> ```

```go
require (
    github.com/aws/aws-sdk-go-v2/aws/protocol/eventstream v1.6.7 // indirect
    github.com/aws/aws-sdk-go-v2/feature/ec2/imds v1.16.21       // indirect
    // ... more indirect dependencies
)
```

**`// indirect`** — These are transitive dependencies (dependencies of your dependencies). Go explicitly lists ALL dependencies, unlike Maven where transitive deps are resolved implicitly.

> **Java equivalent**: These are like the transitive dependencies Maven resolves automatically. Go makes them explicit in `go.mod`, but you don't manage them manually — `go mod tidy` handles it.

**Key go.mod commands** (from terminal):

| Command | What it does | Maven equivalent |
|---------|-------------|-----------------|
| `go mod init ocr-lambda` | Creates go.mod | `mvn archetype:generate` |
| `go mod tidy` | Adds missing deps, removes unused | `mvn dependency:resolve` |
| `go mod download` | Downloads all dependencies | `mvn dependency:go-offline` |
| `go get github.com/foo/bar@v1.2.3` | Adds a specific dependency | Adding `<dependency>` to pom.xml |

There is also a `go.sum` file generated automatically — it contains cryptographic hashes of every dependency (like a lock file). You never edit it manually.

> **Reference**: [Go Modules Reference](https://go.dev/ref/mod)

---

## 3. main.go — The Lambda Function Line by Line

### 3.1 Package Declaration & Imports

```go
package main                    // Line 1
```

Every Go file starts with a `package` declaration. The `main` package is special — it's the entry point for an executable program (like a Java class with `public static void main`). Only the `main` package can have a `main()` function.

> **Java equivalent**: This is like the class that contains `public static void main(String[] args)`.

> **Key difference**: In Java, one file = one public class. In Go, multiple files can share `package main` and all their functions are available to each other without import.

```go
import (                        // Lines 3-22
    "bytes"                     // Standard library — byte buffer manipulation
    "context"                   // Standard library — request-scoped values, cancellation
    "encoding/json"             // Standard library — JSON marshal/unmarshal
    "fmt"                       // Standard library — formatted I/O (like String.format)
    "io"                        // Standard library — I/O interfaces
    "log"                       // Standard library — logging
    "os"                        // Standard library — OS functions, env vars, file I/O
    "os/exec"                   // Standard library — running external commands
    "path/filepath"             // Standard library — file path manipulation
    "strings"                   // Standard library — string utilities

    "github.com/aws/aws-lambda-go/events"        // Lambda event types (S3Event)
    "github.com/aws/aws-lambda-go/lambda"         // Lambda runtime
    "github.com/aws/aws-sdk-go-v2/aws"            // AWS core types
    "github.com/aws/aws-sdk-go-v2/config"         // AWS config loading
    "github.com/aws/aws-sdk-go-v2/credentials"    // AWS credentials
    "github.com/aws/aws-sdk-go-v2/service/s3"     // S3 client
    "github.com/aws/aws-sdk-go-v2/service/sqs"    // SQS client
)
```

Go uses a flat import block with two groups separated by a blank line: standard library first, then third-party packages. Go does NOT have unused imports — if you import something and don't use it, the code won't compile.

> **Java equivalent**:
> ```java
> import java.io.*;
> import java.nio.file.*;
> import com.amazonaws.services.lambda.runtime.*;
> import software.amazon.awssdk.services.s3.*;
> ```

**Standard library highlights for Java developers**:

| Go package | Java equivalent |
|-----------|----------------|
| `fmt` | `String.format()`, `System.out.printf()` |
| `context` | No direct equivalent — closest is `CompletableFuture` cancellation or request-scoped `ThreadLocal` |
| `encoding/json` | Jackson / Gson |
| `os` | `System.getenv()`, `java.io.File` |
| `os/exec` | `Runtime.exec()` / `ProcessBuilder` |
| `strings` | `String` methods + `StringUtils` |
| `io` | `java.io.InputStream`, `java.io.Reader` |
| `log` | `java.util.logging.Logger` / SLF4J |

> **Reference**: [Go Standard Library](https://pkg.go.dev/std)

---

### 3.2 Constants

```go
const (                         // Lines 24-28
    outputBucket = "ocr-output"
    sqsQueueName = "ocr-results"
    tmpDir       = "/tmp"
)
```

`const` declares compile-time constants. In Go, constants are untyped by default — the compiler infers the type from context.

> **Java equivalent**:
> ```java
> private static final String OUTPUT_BUCKET = "ocr-output";
> private static final String SQS_QUEUE_NAME = "ocr-results";
> private static final String TMP_DIR = "/tmp";
> ```

**Note**: Go convention is `camelCase` for unexported (private) constants, NOT `SCREAMING_SNAKE_CASE` like Java. Lowercase first letter = unexported (visible only within this package).

> **Reference**: [Go Constants](https://go.dev/blog/constants)

---

### 3.3 Struct Types (Like Java Classes)

```go
type SQSMessage struct {                            // Lines 31-37
    SourceBucket string `json:"source_bucket"`
    SourceKey    string `json:"source_key"`
    OutputBucket string `json:"output_bucket"`
    OutputKey    string `json:"output_key"`
    TextLength   int    `json:"text_length"`
}
```

A `struct` is Go's version of a Java class, but with important differences. There are no constructors, no `this` keyword, no inheritance. A struct is purely data fields.

**Field declarations**: `FieldName Type` — note the type comes AFTER the name (opposite of Java).

**Struct tags** `` `json:"source_bucket"` `` — These are metadata annotations (like Java's `@JsonProperty("source_bucket")`). The `json` tag tells `encoding/json` what JSON key to use when marshaling/unmarshaling.

> **Java equivalent**:
> ```java
> public class SQSMessage {
>     @JsonProperty("source_bucket")
>     private String sourceBucket;
>
>     @JsonProperty("source_key")
>     private String sourceKey;
>     // ... getters, setters, constructors
> }
> ```

**Uppercase field names** (`SourceBucket`, not `sourceBucket`) — In Go, uppercase first letter means "exported" (public). If you wrote `sourceBucket`, it would be unexported (private to the package) and the JSON encoder couldn't see it.

> **Reference**: [Go Structs](https://go.dev/tour/moretypes/2) | [Struct Tags](https://pkg.go.dev/encoding/json#Marshal)

---

### 3.4 Interfaces (Implicit, Not Explicit)

```go
type S3API interface {                              // Lines 40-43
    GetObject(ctx context.Context, params *s3.GetObjectInput,
        optFns ...func(*s3.Options)) (*s3.GetObjectOutput, error)
    PutObject(ctx context.Context, params *s3.PutObjectInput,
        optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

type SQSAPI interface {                             // Lines 46-49
    GetQueueUrl(ctx context.Context, params *sqs.GetQueueUrlInput,
        optFns ...func(*sqs.Options)) (*sqs.GetQueueUrlOutput, error)
    SendMessage(ctx context.Context, params *sqs.SendMessageInput,
        optFns ...func(*sqs.Options)) (*sqs.SendMessageOutput, error)
}
```

This is one of Go's most powerful and surprising features for Java developers: **interfaces are satisfied implicitly**. There is no `implements` keyword.

Any type that has methods matching all the signatures in an interface automatically satisfies that interface. The real `*s3.Client` from the AWS SDK has `GetObject` and `PutObject` methods, so it automatically satisfies `S3API` — without ever declaring `implements S3API`.

> **Java equivalent**:
> ```java
> public interface S3API {
>     GetObjectOutput getObject(GetObjectInput params);
>     PutObjectOutput putObject(PutObjectInput params);
> }
> // In Java, s3.Client would need: class S3Client implements S3API { ... }
> // In Go, it just needs to have the right methods — no declaration needed
> ```

**Why define these interfaces?** For testing. We can create mock structs that also satisfy `S3API` and inject them instead of the real AWS client. This is the same pattern as Java's dependency injection, but without a DI framework.

**`optFns ...func(*s3.Options)`** — The `...` means variadic parameter (like Java's `String... args`). `func(*s3.Options)` is a function type — Go treats functions as first-class values.

**`*s3.GetObjectInput`** — The `*` means "pointer to". This is like passing an object by reference in Java. In Go, structs are value types by default (copied when passed), so you use pointers to avoid copying and to allow mutation.

> **Reference**: [Go Interfaces](https://go.dev/tour/methods/9) | [Effective Go — Interfaces](https://go.dev/doc/effective_go#interfaces)

---

### 3.5 Function Variables (Mockable Functions)

```go
var RunTesseract = runTesseractReal                 // Line 52
```

This declares a package-level variable `RunTesseract` whose value is the function `runTesseractReal`. Since it's a `var` (not `const`), it can be reassigned — which is exactly what the tests do to inject a mock.

> **Java equivalent**: This is like a `static Function<String, String>` field:
> ```java
> public static Function<String, Pair<String, Exception>> runTesseract = Main::runTesseractReal;
> ```

This is a common Go testing pattern: instead of complex dependency injection frameworks, you simply make the dependency a replaceable function variable.

> **Reference**: [Go Functions as Values](https://go.dev/tour/moretypes/24)

---

### 3.6 The Tesseract OCR Function

```go
func runTesseractReal(imagePath string) (string, error) {  // Line 54
```

**`func`** — keyword for function declaration (like Java's method declaration).

**`(imagePath string)`** — parameter list. Note: type comes AFTER the name.

**`(string, error)`** — Go functions can return MULTIPLE values. This is Go's error handling pattern — instead of throwing exceptions, functions return an error as the last return value. The caller must check it.

> **Java equivalent** of multiple returns: In Java, you'd either throw an exception or return a wrapper object:
> ```java
> // Java would throw:
> public String runTesseract(String imagePath) throws IOException { ... }
> // Or return a result object:
> public Result<String> runTesseract(String imagePath) { ... }
> ```

```go
    outputBase := strings.TrimSuffix(imagePath, filepath.Ext(imagePath))  // Line 55
```

**`:=`** — This is Go's short variable declaration. It declares AND assigns in one step. The type is inferred from the right side.

> **Java equivalent**: `var outputBase = imagePath.replace(ext, "");` (Java 10+ `var` keyword)

**`strings.TrimSuffix`** — Go's string functions are in the `strings` package, called as `strings.FunctionName()`. Unlike Java where `"foo".trim()` is a method on the string object.

```go
    cmd := exec.Command("tesseract", imagePath, outputBase, "--oem", "1", "--psm", "3")  // Line 56
```

Creates an OS command to execute Tesseract CLI. Like Java's `new ProcessBuilder("tesseract", imagePath, ...)`.

The Tesseract flags: `--oem 1` uses the LSTM neural network engine, `--psm 3` enables fully automatic page segmentation.

```go
    var stderr bytes.Buffer         // Line 57
    cmd.Stderr = &stderr            // Line 58
    cmd.Stdout = os.Stdout          // Line 59
```

**`var stderr bytes.Buffer`** — Declares a variable of type `bytes.Buffer` with its zero value (empty buffer). In Go, every type has a zero value — for structs, all fields are zeroed.

**`&stderr`** — The `&` operator takes the address (creates a pointer). `cmd.Stderr` expects an `io.Writer`, and `*bytes.Buffer` satisfies `io.Writer` because it has a `Write` method.

> **Java equivalent**:
> ```java
> ByteArrayOutputStream stderr = new ByteArrayOutputStream();
> process.redirectError(stderr);
> ```

```go
    if err := cmd.Run(); err != nil {               // Line 61
        return "", fmt.Errorf("tesseract failed: %w — stderr: %s", err, stderr.String())  // Line 62
    }
```

**`if err := cmd.Run(); err != nil { }`** — This is Go's idiomatic error handling with an init statement. The `err :=` part declares and assigns in the `if` scope. `nil` means no error (like `null` in Java).

**`fmt.Errorf("... %w ...", err)`** — Creates a new error that wraps the original error. `%w` is special — it allows `errors.Is()` and `errors.Unwrap()` to work (like Java's exception chaining with `new Exception("msg", cause)`).

**`return "", fmt.Errorf(...)`** — Returns empty string and an error. In Go, you always return ALL declared return values, even on error.

> **Java equivalent**:
> ```java
> try {
>     process.waitFor();
> } catch (Exception e) {
>     throw new RuntimeException("tesseract failed: " + stderr, e);
> }
> ```

```go
    outputFile := outputBase + ".txt"               // Line 65
    textBytes, err := os.ReadFile(outputFile)       // Line 66
    if err != nil {                                 // Line 67
        return "", fmt.Errorf("reading tesseract output: %w", err)  // Line 68
    }
    return string(textBytes), nil                   // Line 70
```

**`os.ReadFile`** — Reads entire file into a `[]byte` (byte slice). Returns `([]byte, error)`.

**`string(textBytes)`** — Type conversion from `[]byte` to `string`. Go has explicit type conversions (no implicit casting).

**`return string(textBytes), nil`** — Success: return the text and `nil` (no error).

> **Reference**: [Go Error Handling](https://go.dev/blog/error-handling-and-go) | [os/exec Package](https://pkg.go.dev/os/exec)

---

### 3.7 The Processor Struct & Constructor

```go
type Processor struct {                             // Lines 74-78
    s3Client  S3API
    sqsClient SQSAPI
    queueURL  string
}
```

`Processor` holds the AWS clients and queue URL. Fields are lowercase (unexported) — only accessible within this package. This is like Java's `private` fields.

**Notice**: `s3Client S3API` — the field type is the **interface**, not the concrete type. This is how Go does dependency injection, same principle as in Java: "program to an interface, not an implementation."

```go
func newProcessor(ctx context.Context) (*Processor, error) {  // Line 80
```

**`newProcessor`** — Lowercase `n` means unexported (private). In Go, constructors are just regular functions that return the struct. Convention: `NewFoo` for exported, `newFoo` for unexported.

**`*Processor`** — Returns a pointer to Processor. When you need the caller to share the same instance (not a copy), return a pointer.

**`context.Context`** — Go's way of passing request-scoped data, deadlines, and cancellation signals through the call chain. Almost every function that does I/O or network calls takes a `context.Context` as its first parameter.

> **Java equivalent**:
> ```java
> private Processor(S3Client s3, SQSClient sqs, String queueUrl) { ... }
> public static Processor create() throws Exception { ... }
> ```

> **Reference**: [Go Context](https://go.dev/blog/context)

---

### 3.8 AWS Configuration

```go
    endpoint := os.Getenv("AWS_ENDPOINT_URL")       // Line 81
    region := os.Getenv("AWS_DEFAULT_REGION")        // Line 82
    if region == "" {                                // Line 83
        region = "us-east-1"                         // Line 84
    }
```

`os.Getenv` reads environment variables (like `System.getenv()` in Java). This pattern is used to support both real AWS and LocalStack (which needs a custom endpoint).

```go
    opts := []func(*config.LoadOptions) error{       // Line 87
        config.WithRegion(region),                   // Line 88
    }
```

**`[]func(*config.LoadOptions) error`** — This is a slice (dynamic array) of functions. Each function takes a `*config.LoadOptions` and returns an `error`. This is the AWS SDK's functional options pattern.

> **Java equivalent**: This is like a `List<Consumer<LoadOptions>>`:
> ```java
> List<AwsClientOption> opts = new ArrayList<>();
> opts.add(o -> o.region(Region.US_EAST_1));
> ```

```go
    if endpoint != "" {                              // Line 91
        log.Printf("Using custom endpoint: %s", endpoint)
        opts = append(opts,                          // Line 93
            config.WithCredentialsProvider(
                credentials.NewStaticCredentialsProvider(
                    os.Getenv("AWS_ACCESS_KEY_ID"),
                    os.Getenv("AWS_SECRET_ACCESS_KEY"),
                    "",                              // session token (empty)
                )),
        )
    }
```

**`append(opts, ...)`** — Go's built-in function to add elements to a slice. Slices are Go's primary collection type (like `ArrayList`). There is no `opts.add()` method — `append` is a standalone function.

When a custom endpoint is set (LocalStack), we also provide static credentials.

```go
    cfg, err := config.LoadDefaultConfig(ctx, opts...)  // Line 102
    if err != nil {
        return nil, fmt.Errorf("loading AWS config: %w", err)
    }
```

**`opts...`** — The `...` operator "spreads" the slice into individual arguments (like Java's array-to-varargs).

```go
    s3Opts := func(o *s3.Options) {                  // Line 107
        o.UsePathStyle = true
        if endpoint != "" {
            o.BaseEndpoint = aws.String(endpoint)
        }
    }
```

**Anonymous function** (lambda/closure): This declares a function inline and assigns it to `s3Opts`. It's a closure — it captures the `endpoint` variable from the outer scope.

**`o.UsePathStyle = true`** — Required for LocalStack. Real AWS uses virtual-hosted style (`bucket.s3.amazonaws.com`), LocalStack uses path style (`localhost:4566/bucket`).

**`aws.String(endpoint)`** — Helper that returns a pointer to a string (`*string`). Many AWS SDK fields are `*string` so they can be `nil` (indicating "not set"). This is a common AWS SDK pattern.

> **Java equivalent**: `aws.String(x)` is like calling the AWS SDK builder `.endpointOverride(URI.create(endpoint))`

```go
    s3Client := s3.NewFromConfig(cfg, s3Opts)        // Line 120
    sqsClient := sqs.NewFromConfig(cfg, sqsOpts)     // Line 121
```

Creates the AWS service clients from the loaded config. The second argument is the options function we defined above.

```go
    queueResult, err := sqsClient.GetQueueUrl(ctx, &sqs.GetQueueUrlInput{  // Line 123
        QueueName: aws.String(sqsQueueName),
    })
```

**`&sqs.GetQueueUrlInput{...}`** — Creates a struct literal and takes its address (`&`). The `{...}` is Go's struct initializer (like a constructor call in Java). Fields not mentioned get their zero value.

```go
    return &Processor{                               // Line 130
        s3Client:  s3Client,
        sqsClient: sqsClient,
        queueURL:  *queueResult.QueueUrl,
    }, nil
```

**`*queueResult.QueueUrl`** — Dereferences the pointer. `QueueUrl` is `*string`, and we want the `string` value. The `*` operator is the opposite of `&`.

> **Reference**: [AWS SDK for Go v2](https://aws.github.io/aws-sdk-go-v2/docs/) | [Pointers in Go](https://go.dev/tour/moretypes/1)

---

### 3.9 Core Business Logic — processImage

```go
func (p *Processor) processImage(ctx context.Context, bucket, key string) error {  // Line 137
```

**`(p *Processor)`** — This is a **method receiver**. It's Go's way of attaching methods to types (like a Java method inside a class). `p` is like Java's `this`, and `*Processor` means it operates on a pointer to Processor.

> **Java equivalent**: `public void processImage(String bucket, String key) throws Exception { ... }`
>
> The receiver `(p *Processor)` is essentially:
> ```java
> class Processor {
>     public error processImage(Context ctx, String bucket, String key) { ... }
> }
> ```

**`bucket, key string`** — When consecutive parameters share a type, you can list them with one type declaration.

```go
    localPath, err := p.download(ctx, bucket, key)   // Line 141
    if err != nil {
        return fmt.Errorf("download: %w", err)
    }
    defer os.Remove(localPath)                       // Line 145
```

**`defer os.Remove(localPath)`** — `defer` schedules a function call to execute when the surrounding function returns. It's like Java's `try-finally` or `try-with-resources`, but more flexible.

The deferred call runs no matter how the function returns (normal return or error). This ensures the temp file is always cleaned up.

> **Java equivalent**:
> ```java
> try {
>     // ... use localPath
> } finally {
>     Files.deleteIfExists(localPath);
> }
> ```

```go
    cleaned := strings.TrimSpace(text)               // Line 153
    if cleaned == "" {                               // Line 154
        log.Printf("No text found in %s — skipping", key)
        return nil                                   // Line 156 — return nil = no error, success
    }
```

**Business rule**: If OCR produces no text (blank image), we return `nil` (success) without uploading a file or sending a message. This is a critical part of the spec.

```go
    outKey := deriveOutputKey(key)                   // Line 162
    if err := p.upload(ctx, outputBucket, outKey, cleaned); err != nil {
        return fmt.Errorf("upload: %w", err)
    }

    if err := p.sendMessage(ctx, bucket, key, outputBucket, outKey, len(cleaned)); err != nil {
        return fmt.Errorf("SQS: %w", err)
    }
```

Each step checks for errors immediately. This is Go's "happy path on the left" pattern — errors are handled inline, and the main logic flows downward without nesting.

> **Reference**: [Effective Go — Defer](https://go.dev/doc/effective_go#defer) | [Error Handling](https://go.dev/blog/error-handling-and-go)

---

### 3.10 S3 Download & Upload Methods

```go
func (p *Processor) download(ctx context.Context, bucket, key string) (string, error) {  // Line 176
    result, err := p.s3Client.GetObject(ctx, &s3.GetObjectInput{
        Bucket: aws.String(bucket),
        Key:    aws.String(key),
    })
    if err != nil {
        return "", err
    }
    defer result.Body.Close()                        // Line 184
```

**`defer result.Body.Close()`** — Always close the response body. `defer` ensures this happens even if later code errors. Like Java's `try-with-resources`.

```go
    ext := filepath.Ext(key)                         // Line 186
    if ext == "" {
        ext = ".png"
    }

    localPath := filepath.Join(tmpDir, fmt.Sprintf("ocr-input-%d%s", os.Getpid(), ext))  // Line 191
    data, err := io.ReadAll(result.Body)             // Line 192
```

**`io.ReadAll`** — Reads the entire stream into a `[]byte`. Like Java's `InputStream.readAllBytes()`.

**`fmt.Sprintf`** — Formatted string (like `String.format()`). `%d` = integer, `%s` = string.

**`os.Getpid()`** — Process ID, used to create unique temp file names.

```go
    return localPath, os.WriteFile(localPath, data, 0644)  // Line 197
```

**`0644`** — Unix file permissions (owner read/write, group/other read). This is an octal literal. Like Java's `PosixFilePermission`.

**`os.WriteFile`** returns only an `error`. If it's `nil`, the file was written successfully and `localPath` is the first return value.

```go
func (p *Processor) upload(ctx context.Context, bucket, key, text string) error {  // Line 200
    _, err := p.s3Client.PutObject(ctx, &s3.PutObjectInput{
        Bucket:      aws.String(bucket),
        Key:         aws.String(key),
        Body:        strings.NewReader(text),
        ContentType: aws.String("text/plain; charset=utf-8"),
    })
    return err
}
```

**`_, err := ...`** — The `_` is Go's blank identifier. It discards the first return value (the `*PutObjectOutput`) since we don't need it.

**`strings.NewReader(text)`** — Creates an `io.Reader` from a string. The `Body` field expects an `io.Reader` (like Java's `InputStream`).

---

### 3.11 SQS Message Sending

```go
func (p *Processor) sendMessage(ctx context.Context,
    srcBucket, srcKey, outBucket, outKey string, textLen int) error {  // Line 210

    msg := SQSMessage{                               // Line 211
        SourceBucket: srcBucket,
        SourceKey:    srcKey,
        OutputBucket: outBucket,
        OutputKey:    outKey,
        TextLength:   textLen,
    }
    data, err := json.Marshal(msg)                   // Line 218
```

**`json.Marshal(msg)`** — Serializes the struct to JSON bytes using the `json:"..."` struct tags we defined earlier. Returns `([]byte, error)`.

> **Java equivalent**: `new ObjectMapper().writeValueAsBytes(msg)`

```go
    _, err = p.sqsClient.SendMessage(ctx, &sqs.SendMessageInput{
        QueueUrl:    aws.String(p.queueURL),
        MessageBody: aws.String(string(data)),       // Line 224
    })
    return err
```

**`string(data)`** — Converts `[]byte` to `string`. Then `aws.String(...)` wraps it in a `*string` pointer.

---

### 3.12 Helper Functions

```go
func deriveOutputKey(imageKey string) string {       // Line 229
    ext := filepath.Ext(imageKey)
    return strings.TrimSuffix(imageKey, ext) + ".txt"
}
```

A pure function (no side effects, no receiver). Converts `"photo.png"` → `"photo.txt"`. This is easy to unit test.

```go
func isImageFile(key string) bool {                  // Line 234
    ext := strings.ToLower(filepath.Ext(key))
    switch ext {                                     // Line 236
    case ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp":
        return true
    }
    return false
}
```

**`switch` without explicit `break`** — In Go, `switch` cases do NOT fall through by default (opposite of Java/C). Each `case` automatically breaks. If you want fallthrough, you must explicitly write `fallthrough`.

**Multiple values in one case** — `case ".png", ".jpg", ".jpeg"` matches any of these (like Java 14+ `case "a", "b", "c":`).

---

### 3.13 Lambda Entry Point & main()

```go
func handler(ctx context.Context, s3Event events.S3Event) error {  // Line 243
    proc, err := newProcessor(ctx)
    if err != nil {
        return fmt.Errorf("init processor: %w", err)
    }

    for _, record := range s3Event.Records {         // Line 249
        bucket := record.S3.Bucket.Name
        key := record.S3.Object.Key
```

**`for _, record := range s3Event.Records`** — Go's `range` iterates over a slice. It returns `(index, value)`. The `_` discards the index since we don't need it.

> **Java equivalent**: `for (S3EventRecord record : s3Event.getRecords()) { ... }`

```go
        if !isImageFile(key) {
            log.Printf("Skipping non-image: %s", key)
            continue
        }

        if err := proc.processImage(ctx, bucket, key); err != nil {
            log.Printf("ERROR %s/%s: %v", bucket, key, err)
            return err
        }
    }
    return nil
}
```

**`%v`** — Go's default format verb. Prints the value in a default format. For errors, it calls `.Error()`.

```go
func main() {                                        // Line 266
    log.SetFlags(log.LstdFlags | log.Lshortfile)
    log.Printf("OCR Lambda starting — endpoint=%s region=%s",
        os.Getenv("AWS_ENDPOINT_URL"), os.Getenv("AWS_DEFAULT_REGION"))
    lambda.Start(handler)                            // Line 270
}
```

**`func main()`** — The program entry point. Every executable Go program must have exactly one `main` function in `package main`.

**`log.SetFlags(log.LstdFlags | log.Lshortfile)`** — Configures the logger to include date/time and shortened file name. The `|` is bitwise OR (same as Java).

**`lambda.Start(handler)`** — Registers our `handler` function with the Lambda runtime and starts listening for invocations. This never returns during normal execution.

> **Reference**: [AWS Lambda Go](https://docs.aws.amazon.com/lambda/latest/dg/lambda-golang.html) | [lambda-go Package](https://pkg.go.dev/github.com/aws/aws-lambda-go/lambda)

---

## 4. main_test.go — Unit Tests Line by Line

Go has a built-in testing framework — no JUnit needed. Test files end in `_test.go` and are in the same package.

### 4.1 Mock Implementations

```go
package main                                         // Line 1 — same package as the code under test
```

**Same package** — This gives tests access to unexported (lowercase) functions and types. In Java, this is like putting tests in the same package for package-private access.

```go
type mockS3 struct {                                 // Line 17
    getBody       []byte
    uploadedFiles map[string]string
}

func newMockS3(img []byte) *mockS3 {                 // Line 22
    return &mockS3{getBody: img, uploadedFiles: make(map[string]string)}
}
```

**`map[string]string`** — Go's built-in hash map (like `HashMap<String, String>`).

**`make(map[string]string)`** — `make` allocates and initializes maps, slices, and channels. You must `make` a map before using it (a `nil` map panics on write).

```go
func (m *mockS3) GetObject(_ context.Context, p *s3.GetObjectInput,
    _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {  // Line 26
    return &s3.GetObjectOutput{
        Body: io.NopCloser(bytes.NewReader(m.getBody)),
    }, nil
}
```

**`_ context.Context`** — The `_` means "I accept this parameter but won't use it." Go requires you to either use a parameter or explicitly discard it.

**`io.NopCloser`** — Wraps a `Reader` into a `ReadCloser` where `Close()` does nothing. The S3 response body is a `ReadCloser`, so our mock must match.

Because `mockS3` has `GetObject` and `PutObject` methods with the right signatures, it **implicitly satisfies** the `S3API` interface. No `implements` declaration needed.

```go
func (m *mockS3) PutObject(_ context.Context, p *s3.PutObjectInput,
    _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {  // Line 30
    buf := new(bytes.Buffer)
    buf.ReadFrom(p.Body)
    m.uploadedFiles[*p.Key] = buf.String()
    return &s3.PutObjectOutput{}, nil
}
```

**`m.uploadedFiles[*p.Key] = buf.String()`** — Map assignment. `*p.Key` dereferences the `*string` pointer to get the key string. This captures what was "uploaded" so tests can verify it.

---

### 4.2 Table-Driven Tests

```go
func TestDeriveOutputKey(t *testing.T) {             // Line 52
    cases := map[string]string{
        "photo.png":                "photo.txt",
        "uploads/image.jpg":       "uploads/image.txt",
        "path/to/scan.tiff":       "path/to/scan.txt",
        "file.name.with.dots.png": "file.name.with.dots.txt",
    }
    for in, want := range cases {
        if got := deriveOutputKey(in); got != want {
            t.Errorf("deriveOutputKey(%q)=%q want %q", in, got, want)
        }
    }
}
```

**`func TestXxx(t *testing.T)`** — Go test functions must start with `Test` and take a `*testing.T` parameter. The `go test` command finds and runs these automatically.

> **Java equivalent** (JUnit):
> ```java
> @Test
> void testDeriveOutputKey() {
>     assertEquals("photo.txt", deriveOutputKey("photo.png"));
> }
> ```

**`t.Errorf`** — Reports a test failure but continues running (like JUnit's `assertAll`). Use `t.Fatalf` to stop the test immediately (like `fail()`).

**`%q`** — Quoted string format. Prints `"photo.txt"` with quotes, making test output more readable.

**Table-driven tests** are Go's idiomatic pattern for testing multiple inputs. You define a map or slice of test cases and loop over them.

---

### 4.3 Testing With Mocked Dependencies

```go
func TestProcessImage_WithText(t *testing.T) {       // Line 81
    orig := RunTesseract                             // Save original
    defer func() { RunTesseract = orig }()           // Restore after test
    RunTesseract = func(_ string) (string, error) {  // Replace with mock
        return "Hello OCR", nil
    }
```

**Mock injection pattern**: Save the original function, `defer` its restoration, then replace it with a mock. This ensures the mock is always cleaned up, even if the test fails.

> **Java equivalent** (Mockito):
> ```java
> @Mock TesseractService tesseract;
> when(tesseract.run(any())).thenReturn("Hello OCR");
> ```

```go
    ms3 := newMockS3([]byte("fake-img"))
    msqs := &mockSQS{}
    p := &Processor{s3Client: ms3, sqsClient: msqs, queueURL: "http://q"}
```

Direct construction with mock dependencies. No DI framework, no annotations — just plain struct initialization.

```go
    if err := p.processImage(context.Background(), "ocr-uploads", "test.png"); err != nil {
        t.Fatal(err)                                 // Fail immediately if error
    }

    if txt, ok := ms3.uploadedFiles["test.txt"]; !ok {
        t.Fatal("no txt uploaded")
    } else if txt != "Hello OCR" {
        t.Errorf("got %q", txt)
    }
```

**`txt, ok := ms3.uploadedFiles["test.txt"]`** — Map lookup returns two values: the value and a boolean indicating if the key exists. This is called the "comma ok" idiom.

> **Java equivalent**: 
> ```java
> String txt = uploadedFiles.get("test.txt");
> assertNotNull(txt);
> assertEquals("Hello OCR", txt);
> ```

**Running tests**: `go test -v ./...` (the `-v` flag is verbose, `./...` means all packages recursively).

> **Reference**: [Go Testing](https://go.dev/doc/tutorial/add-a-test) | [Testing Package](https://pkg.go.dev/testing)

---

## 5. Building & Running

```bash
# Run unit tests
go test -v ./...

# Build binary for Linux (Lambda target)
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -tags lambda.norpc -o bootstrap main.go

# Build flags explained:
#   CGO_ENABLED=0  — Pure Go, no C dependencies (needed for cross-compile)
#   GOOS=linux     — Target OS
#   GOARCH=amd64   — Target architecture
#   -tags lambda.norpc — Use the newer Lambda runtime API (no net/rpc)
#   -o bootstrap   — Output binary name (Lambda expects "bootstrap")
```

> **Java equivalent**: `mvn package -Dplatform=linux` then upload the JAR to Lambda.

---

## 6. Reference Links

**Go Language**:
- [A Tour of Go (Interactive Tutorial)](https://go.dev/tour/)
- [Effective Go](https://go.dev/doc/effective_go)
- [Go by Example](https://gobyexample.com/)
- [Go for Java Programmers](https://go.dev/wiki/FromJavaToComeToGo)
- [Go Standard Library](https://pkg.go.dev/std)

**Go Modules & Dependencies**:
- [Go Modules Reference](https://go.dev/ref/mod)
- [Managing Dependencies](https://go.dev/doc/modules/managing-dependencies)

**AWS SDK for Go v2**:
- [Getting Started](https://aws.github.io/aws-sdk-go-v2/docs/getting-started/)
- [S3 Package Docs](https://pkg.go.dev/github.com/aws/aws-sdk-go-v2/service/s3)
- [SQS Package Docs](https://pkg.go.dev/github.com/aws/aws-sdk-go-v2/service/sqs)
- [Lambda Go Runtime](https://pkg.go.dev/github.com/aws/aws-lambda-go)

**Go Testing**:
- [Add a Test (Tutorial)](https://go.dev/doc/tutorial/add-a-test)
- [Testing Package](https://pkg.go.dev/testing)
- [Table-Driven Tests](https://go.dev/wiki/TableDrivenTests)

**Tesseract OCR**:
- [Tesseract Documentation](https://tesseract-ocr.github.io/)
- [Tesseract Man Page (CLI flags)](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
