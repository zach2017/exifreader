package com.ocr.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * Response models matching the JSON returned by each Lambda handler.
 * All are records (immutable, auto-generated equals/hashCode/toString).
 */
public final class OcrResponse {

    private OcrResponse() {} // namespace only

    // ---------------------------------------------------------------
    // handler.py response
    // ---------------------------------------------------------------

    /**
     * Response from the image OCR handler.
     *
     * @param text           extracted text (null on error)
     * @param filename       original filename echoed back
     * @param textLength     character count
     * @param wordCount      word count
     * @param processingTimeMs  OCR duration in milliseconds
     * @param error          error message (null on success)
     */
    public record ImageOcrResult(
            String text,
            String filename,
            @SerializedName("text_length") int textLength,
            @SerializedName("word_count") int wordCount,
            @SerializedName("processing_time_ms") double processingTimeMs,
            String error
    ) {
        public boolean isSuccess() { return error == null; }
    }

    // ---------------------------------------------------------------
    // pdf_handler.py response
    // ---------------------------------------------------------------

    public record PageResult(
            int page,
            String text,
            @SerializedName("word_count") int wordCount,
            @SerializedName("char_count") int charCount,
            @SerializedName("extraction_time_ms") double extractionTimeMs
    ) {}

    /**
     * Response from the PDF text extraction handler.
     */
    public record PdfExtractResult(
            String text,
            String filename,
            @SerializedName("page_count") int pageCount,
            @SerializedName("total_word_count") int totalWordCount,
            @SerializedName("total_char_count") int totalCharCount,
            @SerializedName("processing_time_ms") double processingTimeMs,
            @SerializedName("file_size_bytes") long fileSizeBytes,
            List<PageResult> pages,
            String error
    ) {
        public boolean isSuccess() { return error == null; }
    }

    // ---------------------------------------------------------------
    // pdf_ocr_handler.py response
    // ---------------------------------------------------------------

    public record OcrPageResult(
            int page,
            String text,
            @SerializedName("word_count") int wordCount,
            @SerializedName("char_count") int charCount,
            @SerializedName("image_extract_ms") double imageExtractMs,
            @SerializedName("ocr_ms") double ocrMs,
            @SerializedName("page_total_ms") double pageTotalMs,
            @SerializedName("image_size_bytes") long imageSizeBytes
    ) {}

    public record TimingBreakdown(
            @SerializedName("pipeline_ms") double pipelineMs,
            @SerializedName("total_image_extract_ms") double totalImageExtractMs,
            @SerializedName("total_ocr_ms") double totalOcrMs,
            @SerializedName("avg_extract_per_page_ms") double avgExtractPerPageMs,
            @SerializedName("avg_ocr_per_page_ms") double avgOcrPerPageMs
    ) {}

    /**
     * Response from the PDF OCR pipeline handler.
     */
    public record PdfOcrResult(
            String text,
            String filename,
            @SerializedName("page_count") int pageCount,
            @SerializedName("total_word_count") int totalWordCount,
            @SerializedName("total_char_count") int totalCharCount,
            TimingBreakdown timing,
            @SerializedName("pdf_size_bytes") long pdfSizeBytes,
            int dpi,
            List<OcrPageResult> pages,
            String error
    ) {
        public boolean isSuccess() { return error == null; }
    }
}
