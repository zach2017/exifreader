package com.ocr;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.ocr.client.LambdaInvoker;
import com.ocr.model.OcrRequest;
import com.ocr.model.OcrResponse.*;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class ModelAndPayloadTest {

    private static final Gson GSON = new GsonBuilder().create();

    // ── OcrRequest records ──────────────────────────────────────

    @Test
    void imageOcrRequest_holdsValues() {
        var req = new OcrRequest.ImageOcr("b64data", "photo.png");
        assertEquals("b64data", req.image());
        assertEquals("photo.png", req.filename());
    }

    @Test
    void pdfOcrRequest_defaultDpi() {
        var req = new OcrRequest.PdfOcr("b64", "file.pdf");
        assertEquals(300, req.dpi());
    }

    @Test
    void pdfOcrRequest_customDpi() {
        var req = new OcrRequest.PdfOcr("b64", "file.pdf", 600);
        assertEquals(600, req.dpi());
    }

    @Test
    void sealedInterface_exhaustiveSwitch() {
        OcrRequest req = new OcrRequest.ImageOcr("x", "y");
        String result = switch (req) {
            case OcrRequest.ImageOcr img   -> "image";
            case OcrRequest.PdfExtract pdf -> "pdf";
            case OcrRequest.PdfOcr ocr     -> "pdfocr";
        };
        assertEquals("image", result);
    }

    // ── Payload builders ────────────────────────────────────────

    @Test
    void buildImagePayload_containsExpectedFields() {
        var req = new OcrRequest.ImageOcr("abc123", "test.png");
        String json = LambdaInvoker.buildImagePayload(req);

        assertTrue(json.contains("\"image\""));
        assertTrue(json.contains("abc123"));
        assertTrue(json.contains("test.png"));
    }

    @Test
    void buildPdfExtractPayload_containsExpectedFields() {
        var req = new OcrRequest.PdfExtract("pdfdata", "doc.pdf");
        String json = LambdaInvoker.buildPdfExtractPayload(req);

        assertTrue(json.contains("\"pdf\""));
        assertTrue(json.contains("pdfdata"));
        assertTrue(json.contains("doc.pdf"));
    }

    @Test
    void buildPdfOcrPayload_includesDpi() {
        var req = new OcrRequest.PdfOcr("data", "scan.pdf", 600);
        String json = LambdaInvoker.buildPdfOcrPayload(req);

        assertTrue(json.contains("\"dpi\""));
        assertTrue(json.contains("600"));
    }

    // ── Response deserialization ────────────────────────────────

    @Test
    void imageOcrResult_deserializesFromJson() {
        String json = """
                {
                    "text": "Hello World",
                    "filename": "test.png",
                    "text_length": 11,
                    "word_count": 2,
                    "processing_time_ms": 145.5
                }
                """;

        ImageOcrResult result = GSON.fromJson(json, ImageOcrResult.class);

        assertTrue(result.isSuccess());
        assertEquals("Hello World", result.text());
        assertEquals(2, result.wordCount());
        assertEquals(145.5, result.processingTimeMs());
    }

    @Test
    void imageOcrResult_errorCase() {
        String json = """
                { "error": "No image data provided" }
                """;

        ImageOcrResult result = GSON.fromJson(json, ImageOcrResult.class);

        assertFalse(result.isSuccess());
        assertEquals("No image data provided", result.error());
    }

    @Test
    void pdfExtractResult_deserializesWithPages() {
        String json = """
                {
                    "text": "Page 1 text\\n\\nPage 2 text",
                    "filename": "doc.pdf",
                    "page_count": 2,
                    "total_word_count": 6,
                    "total_char_count": 26,
                    "processing_time_ms": 50.0,
                    "file_size_bytes": 1024,
                    "pages": [
                        { "page": 1, "text": "Page 1 text", "word_count": 3, "char_count": 11, "extraction_time_ms": 20.0 },
                        { "page": 2, "text": "Page 2 text", "word_count": 3, "char_count": 11, "extraction_time_ms": 15.0 }
                    ]
                }
                """;

        PdfExtractResult result = GSON.fromJson(json, PdfExtractResult.class);

        assertTrue(result.isSuccess());
        assertEquals(2, result.pageCount());
        assertEquals(2, result.pages().size());
        assertEquals(3, result.pages().getFirst().wordCount());
    }

    @Test
    void pdfOcrResult_deserializesTimingBreakdown() {
        String json = """
                {
                    "text": "OCR text",
                    "filename": "scan.pdf",
                    "page_count": 1,
                    "total_word_count": 2,
                    "total_char_count": 8,
                    "timing": {
                        "pipeline_ms": 500.0,
                        "total_image_extract_ms": 100.0,
                        "total_ocr_ms": 350.0,
                        "avg_extract_per_page_ms": 100.0,
                        "avg_ocr_per_page_ms": 350.0
                    },
                    "pdf_size_bytes": 2048,
                    "dpi": 300,
                    "pages": [
                        {
                            "page": 1,
                            "text": "OCR text",
                            "word_count": 2,
                            "char_count": 8,
                            "image_extract_ms": 100.0,
                            "ocr_ms": 350.0,
                            "page_total_ms": 460.0,
                            "image_size_bytes": 50000
                        }
                    ]
                }
                """;

        PdfOcrResult result = GSON.fromJson(json, PdfOcrResult.class);

        assertTrue(result.isSuccess());
        assertEquals(300, result.dpi());
        assertNotNull(result.timing());
        assertEquals(500.0, result.timing().pipelineMs());
        assertEquals(350.0, result.timing().totalOcrMs());
        assertEquals(50000, result.pages().getFirst().imageSizeBytes());
    }
}
