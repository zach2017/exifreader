package com.ocr.model;

/**
 * Sealed hierarchy representing the three types of OCR requests
 * that map to the three Lambda handlers.
 *
 * <p>Uses Java 21 records for immutable data carriers and sealed
 * interfaces for exhaustive pattern matching in switch expressions.</p>
 */
public sealed interface OcrRequest {

    /** Image OCR request → handler.py (lambda_handler). */
    record ImageOcr(String image, String filename) implements OcrRequest {}

    /** PDF text extraction request → pdf_handler.py (pdf_handler). */
    record PdfExtract(String pdf, String filename) implements OcrRequest {}

    /** PDF OCR (render + Tesseract) request → pdf_ocr_handler.py (pdf_ocr_handler). */
    record PdfOcr(String pdf, String filename, int dpi) implements OcrRequest {
        public PdfOcr(String pdf, String filename) {
            this(pdf, filename, 300);
        }
    }
}
