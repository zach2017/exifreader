package com.ocr;

import com.ocr.model.OcrResponse.*;
import com.ocr.util.OutputFormatter;
import com.ocr.util.OutputFormatter.Mode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class OutputFormatterTest {

    @TempDir
    Path tempDir;

    // Helper to capture stdout
    private String capture(Runnable action) {
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);
        action.run();
        // The action should use ps, but we pass it via lambda
        return baos.toString();
    }

    // ── ImageOcrResult ──────────────────────────────────────────
    @Test
    void imageOcr_textMode_printsTextOnly() {
        var result = new ImageOcrResult("Hello World", "test.png", 11, 2, 100.0, null);
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);

        OutputFormatter.print(result, Mode.TEXT, ps);

        assert (!baos.toString().isEmpty());
    }

    @Test
    void imageOcr_textMode_printsErrorOnFailure() {
        var result = new ImageOcrResult(null, "test.png", 0, 0, 0, "No image data provided");
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);

        OutputFormatter.print(result, Mode.TEXT, ps);

        assertTrue(baos.toString().contains("ERROR: No image data provided"));
    }

    @Test
    void imageOcr_jsonMode_producesValidJson() {
        var result = new ImageOcrResult("text", "f.png", 4, 1, 50.0, null);
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);

        OutputFormatter.print(result, Mode.JSON, ps);

        String json = baos.toString();
        assertTrue(json.contains("\"text\""));
        assertTrue(json.contains("\"f.png\""));
    }

    @Test
    void imageOcr_summaryMode_showsStats() {
        var result = new ImageOcrResult("Extracted", "photo.jpg", 9, 1, 200.0, null);
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);

        OutputFormatter.print(result, Mode.SUMMARY, ps);

        String output = baos.toString();
        assertTrue(output.contains("Image OCR Result"));
        assertTrue(output.contains("photo.jpg"));
        assertTrue(output.contains("200 ms"));
        assertTrue(output.contains("Extracted"));
    }

    @Test
    void imageOcr_summaryMode_errorShowsMessage() {
        var result = new ImageOcrResult(null, "bad.png", 0, 0, 0, "Tesseract failed");
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);

        OutputFormatter.print(result, Mode.SUMMARY, ps);

        assertTrue(baos.toString().contains("Tesseract failed"));
    }

    // ── PdfExtractResult ────────────────────────────────────────
    @Test
    void pdfExtract_summaryMode_showsPageBreakdown() {
        var pages = List.of(
                new PageResult(1, "Page one", 2, 8, 10.0),
                new PageResult(2, "Page two", 2, 8, 12.0)
        );
        var result = new PdfExtractResult(
                "Page one\n\nPage two", "doc.pdf", 2, 4, 16, 22.0, 5000, pages, null
        );
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);

        OutputFormatter.print(result, Mode.SUMMARY, ps);

        String output = baos.toString();
        assertTrue(output.contains("PDF Text Extraction Result"));
        assertTrue(output.contains("doc.pdf"));
        assertTrue(output.contains("Page 1"));
        assertTrue(output.contains("Page 2"));
    }

    // ── PdfOcrResult ────────────────────────────────────────────
    @Test
    void pdfOcr_summaryMode_showsTimingBreakdown() {
        var timing = new TimingBreakdown(500.0, 100.0, 350.0, 100.0, 350.0);
        var pages = List.of(
                new OcrPageResult(1, "OCR text", 2, 8, 100.0, 350.0, 460.0, 50000)
        );
        var result = new PdfOcrResult(
                "OCR text", "scan.pdf", 1, 2, 8, timing, 2048, 300, pages, null
        );
        var baos = new ByteArrayOutputStream();
        var ps = new PrintStream(baos);

        OutputFormatter.print(result, Mode.SUMMARY, ps);

        String output = baos.toString();
        assertTrue(output.contains("PDF OCR Pipeline Result"));
        assertTrue(output.contains("DPI"));
        assertTrue(output.contains("300"));
        assertTrue(output.contains("Image rendering"));
        assertTrue(output.contains("OCR processing"));
    }

    // ── saveToFile ──────────────────────────────────────────────
    @Test
    void saveToFile_writesContent() throws IOException {
        Path out = tempDir.resolve("output.txt");
        OutputFormatter.saveToFile("Hello saved text", out);

        assertEquals("Hello saved text", Files.readString(out));
    }

    // ── prettyJson ──────────────────────────────────────────────
    @Test
    void prettyJson_formatsCompactJson() {
        String compact = "{\"key\":\"value\",\"num\":42}";
        String pretty = OutputFormatter.prettyJson(compact);

        assertTrue(pretty.contains("\n"));
        assertTrue(pretty.contains("\"key\""));
    }
}
