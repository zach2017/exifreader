package com.ocr.client;

import com.ocr.model.OcrRequest;
import com.ocr.model.OcrResponse.*;
import com.ocr.util.FileUtils;
import com.ocr.util.FileUtils.FileType;
import com.ocr.util.OutputFormatter;
import com.ocr.util.OutputFormatter.Mode;
import picocli.CommandLine;
import picocli.CommandLine.*;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.Callable;

/**
 * CLI entry point for the OCR Lambda client.
 *
 * <p>Usage examples:
 * <pre>
 *   # Auto-detect: image → image OCR, PDF → text extraction
 *   ocr-client scan invoice.pdf
 *
 *   # Force PDF OCR pipeline (for scanned PDFs)
 *   ocr-client pdf-ocr scanned-doc.pdf --dpi 600
 *
 *   # Image OCR with JSON output
 *   ocr-client image receipt.jpg --output json
 *
 *   # Save extracted text to file
 *   ocr-client scan report.pdf --save-to report.txt
 * </pre>
 * </p>
 */
@Command(
        name = "ocr-client",
        description = "CLI client for OCR Lambda functions",
        version = "ocr-client 1.0.0",
        mixinStandardHelpOptions = true,
        subcommands = {
                OcrCli.ScanCommand.class,
                OcrCli.ImageCommand.class,
                OcrCli.PdfExtractCommand.class,
                OcrCli.PdfOcrCommand.class,
        }
)
public class OcrCli implements Runnable {

    @Spec
    Model.CommandSpec spec;

    @Override
    public void run() {
        spec.commandLine().usage(System.out);
    }

    public static void main(String[] args) {
        int exitCode = new CommandLine(new OcrCli()).execute(args);
        System.exit(exitCode);
    }

    // ===============================================================
    //  Shared options mixin
    // ===============================================================

    static class SharedOptions {
        @Option(names = {"-r", "--region"}, description = "AWS region (default: ${DEFAULT-VALUE})",
                defaultValue = "${OCR_AWS_REGION:-us-east-1}")
        String region;

        @Option(names = {"--image-fn"}, description = "Image OCR Lambda function name",
                defaultValue = "${OCR_IMAGE_FUNCTION:-ocr-image}")
        String imageFn;

        @Option(names = {"--pdf-fn"}, description = "PDF extract Lambda function name",
                defaultValue = "${OCR_PDF_FUNCTION:-ocr-pdf}")
        String pdfFn;

        @Option(names = {"--pdf-ocr-fn"}, description = "PDF OCR Lambda function name",
                defaultValue = "${OCR_PDF_OCR_FUNCTION:-ocr-pdf-ocr}")
        String pdfOcrFn;

        @Option(names = {"-o", "--output"}, description = "Output format: summary, text, json (default: ${DEFAULT-VALUE})",
                defaultValue = "summary")
        Mode outputMode;

        @Option(names = {"-s", "--save-to"}, description = "Save extracted text to file")
        Path saveTo;

        @Option(names = {"--max-size"}, description = "Max file size in MB (default: ${DEFAULT-VALUE})",
                defaultValue = "10")
        int maxSizeMb;

        LambdaInvoker buildInvoker() {
            return new LambdaInvoker(region, imageFn, pdfFn, pdfOcrFn);
        }
    }

    // ===============================================================
    //  scan – auto-detect file type
    // ===============================================================

    @Command(name = "scan", description = "Auto-detect file type and call the right Lambda")
    static class ScanCommand implements Callable<Integer> {

        @Parameters(index = "0", description = "File to process (image or PDF)")
        Path file;

        @Mixin
        SharedOptions opts;

        @Option(names = {"--force-ocr"}, description = "Force PDF OCR pipeline even for digital PDFs")
        boolean forceOcr;

        @Option(names = {"--dpi"}, description = "DPI for PDF OCR rendering (default: 300)",
                defaultValue = "300")
        int dpi;

        @Override
        public Integer call() throws Exception {
            validateFile(file);

            FileType type = FileUtils.detectType(file);

            return switch (type) {
                case IMAGE   -> processImage(file, opts);
                case PDF     -> forceOcr
                        ? processPdfOcr(file, dpi, opts)
                        : processPdfExtract(file, opts);
                case UNKNOWN -> {
                    System.err.println("Unsupported file type: " + file.getFileName());
                    System.err.println("Supported: PNG, JPG, TIFF, BMP, GIF, WEBP, PDF");
                    yield 1;
                }
            };
        }
    }

    // ===============================================================
    //  image – explicit image OCR
    // ===============================================================

    @Command(name = "image", description = "OCR an image file via Tesseract Lambda")
    static class ImageCommand implements Callable<Integer> {

        @Parameters(index = "0", description = "Image file (PNG, JPG, TIFF, etc.)")
        Path file;

        @Mixin
        SharedOptions opts;

        @Override
        public Integer call() throws Exception {
            validateFile(file);
            return processImage(file, opts);
        }
    }

    // ===============================================================
    //  pdf-extract – digital PDF text extraction
    // ===============================================================

    @Command(name = "pdf-extract", description = "Extract embedded text from a digital PDF")
    static class PdfExtractCommand implements Callable<Integer> {

        @Parameters(index = "0", description = "PDF file")
        Path file;

        @Mixin
        SharedOptions opts;

        @Override
        public Integer call() throws Exception {
            validateFile(file);
            return processPdfExtract(file, opts);
        }
    }

    // ===============================================================
    //  pdf-ocr – scanned PDF OCR pipeline
    // ===============================================================

    @Command(name = "pdf-ocr", description = "OCR a scanned PDF (render pages to images, then Tesseract)")
    static class PdfOcrCommand implements Callable<Integer> {

        @Parameters(index = "0", description = "PDF file")
        Path file;

        @Option(names = {"--dpi"}, description = "Render DPI (default: 300)", defaultValue = "300")
        int dpi;

        @Mixin
        SharedOptions opts;

        @Override
        public Integer call() throws Exception {
            validateFile(file);
            return processPdfOcr(file, dpi, opts);
        }
    }

    // ===============================================================
    //  Shared processing logic
    // ===============================================================

    private static int processImage(Path file, SharedOptions opts) throws IOException {
        String b64 = FileUtils.readAsBase64(file, opts.maxSizeMb);
        String filename = file.getFileName().toString();

        System.err.printf("Sending %s (%s) to image OCR Lambda...%n",
                filename, FileUtils.formatSize(Files.size(file)));

        try (var invoker = opts.buildInvoker()) {
            var request = new OcrRequest.ImageOcr(b64, filename);
            ImageOcrResult result = invoker.invokeImageOcr(request);

            OutputFormatter.print(result, opts.outputMode, System.out);
            maybeSave(result.text(), opts.saveTo);
            return result.isSuccess() ? 0 : 1;
        }
    }

    private static int processPdfExtract(Path file, SharedOptions opts) throws IOException {
        String b64 = FileUtils.readAsBase64(file, opts.maxSizeMb);
        String filename = file.getFileName().toString();

        System.err.printf("Sending %s (%s) to PDF text extraction Lambda...%n",
                filename, FileUtils.formatSize(Files.size(file)));

        try (var invoker = opts.buildInvoker()) {
            var request = new OcrRequest.PdfExtract(b64, filename);
            PdfExtractResult result = invoker.invokePdfExtract(request);

            OutputFormatter.print(result, opts.outputMode, System.out);
            maybeSave(result.text(), opts.saveTo);
            return result.isSuccess() ? 0 : 1;
        }
    }

    private static int processPdfOcr(Path file, int dpi, SharedOptions opts) throws IOException {
        String b64 = FileUtils.readAsBase64(file, opts.maxSizeMb);
        String filename = file.getFileName().toString();

        System.err.printf("Sending %s (%s) to PDF OCR Lambda (DPI=%d)...%n",
                filename, FileUtils.formatSize(Files.size(file)), dpi);

        try (var invoker = opts.buildInvoker()) {
            var request = new OcrRequest.PdfOcr(b64, filename, dpi);
            PdfOcrResult result = invoker.invokePdfOcr(request);

            OutputFormatter.print(result, opts.outputMode, System.out);
            maybeSave(result.text(), opts.saveTo);
            return result.isSuccess() ? 0 : 1;
        }
    }

    // ===============================================================
    //  Helpers
    // ===============================================================

    private static void validateFile(Path file) {
        if (!Files.exists(file)) {
            throw new ParameterException(
                    new CommandLine(new OcrCli()),
                    "File not found: " + file
            );
        }
        if (!Files.isRegularFile(file)) {
            throw new ParameterException(
                    new CommandLine(new OcrCli()),
                    "Not a regular file: " + file
            );
        }
    }

    private static void maybeSave(String text, Path saveTo) throws IOException {
        if (saveTo != null && text != null) {
            OutputFormatter.saveToFile(text, saveTo);
            System.err.printf("Saved extracted text to %s%n", saveTo);
        }
    }
}
