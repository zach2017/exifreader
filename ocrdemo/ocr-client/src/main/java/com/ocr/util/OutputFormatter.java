package com.ocr.util;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonParser;
import com.ocr.model.OcrResponse.*;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Formats Lambda responses for CLI output.
 * Supports three modes: raw JSON, text-only, and human-readable summary.
 */
public final class OutputFormatter {

    private OutputFormatter() {}

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    public enum Mode { JSON, TEXT, SUMMARY }

    // ---------------------------------------------------------------
    // Image OCR result
    // ---------------------------------------------------------------

    public static void print(ImageOcrResult result, Mode mode, PrintStream out) {
        switch (mode) {
            case JSON    -> out.println(GSON.toJson(result));
            case TEXT    -> out.println(result.isSuccess() ? result.text() : "ERROR: " + result.error());
            case SUMMARY -> {
                if (!result.isSuccess()) {
                    out.println("❌ Error: " + result.error());
                    return;
                }
                out.println("─".repeat(60));
                out.println("  Image OCR Result");
                out.println("─".repeat(60));
                out.printf("  File:       %s%n", result.filename());
                out.printf("  Words:      %,d%n", result.wordCount());
                out.printf("  Characters: %,d%n", result.textLength());
                out.printf("  Time:       %.0f ms%n", result.processingTimeMs());
                out.println("─".repeat(60));
                out.println(result.text());
            }
        }
    }

    // ---------------------------------------------------------------
    // PDF extract result
    // ---------------------------------------------------------------

    public static void print(PdfExtractResult result, Mode mode, PrintStream out) {
        switch (mode) {
            case JSON    -> out.println(GSON.toJson(result));
            case TEXT    -> out.println(result.isSuccess() ? result.text() : "ERROR: " + result.error());
            case SUMMARY -> {
                if (!result.isSuccess()) {
                    out.println("❌ Error: " + result.error());
                    return;
                }
                out.println("─".repeat(60));
                out.println("  PDF Text Extraction Result");
                out.println("─".repeat(60));
                out.printf("  File:       %s%n", result.filename());
                out.printf("  Pages:      %d%n", result.pageCount());
                out.printf("  Words:      %,d%n", result.totalWordCount());
                out.printf("  Characters: %,d%n", result.totalCharCount());
                out.printf("  File size:  %s%n", FileUtils.formatSize(result.fileSizeBytes()));
                out.printf("  Time:       %.0f ms%n", result.processingTimeMs());
                out.println("─".repeat(60));

                if (result.pages() != null) {
                    for (var page : result.pages()) {
                        out.printf("%n── Page %d (%d words, %.0f ms) ──%n", page.page(), page.wordCount(), page.extractionTimeMs());
                        out.println(page.text());
                    }
                } else {
                    out.println(result.text());
                }
            }
        }
    }

    // ---------------------------------------------------------------
    // PDF OCR result
    // ---------------------------------------------------------------

    public static void print(PdfOcrResult result, Mode mode, PrintStream out) {
        switch (mode) {
            case JSON    -> out.println(GSON.toJson(result));
            case TEXT    -> out.println(result.isSuccess() ? result.text() : "ERROR: " + result.error());
            case SUMMARY -> {
                if (!result.isSuccess()) {
                    out.println("❌ Error: " + result.error());
                    return;
                }
                out.println("─".repeat(60));
                out.println("  PDF OCR Pipeline Result");
                out.println("─".repeat(60));
                out.printf("  File:       %s%n", result.filename());
                out.printf("  Pages:      %d%n", result.pageCount());
                out.printf("  DPI:        %d%n", result.dpi());
                out.printf("  Words:      %,d%n", result.totalWordCount());
                out.printf("  Characters: %,d%n", result.totalCharCount());
                out.printf("  PDF size:   %s%n", FileUtils.formatSize(result.pdfSizeBytes()));

                if (result.timing() != null) {
                    var t = result.timing();
                    out.println();
                    out.println("  Timing breakdown:");
                    out.printf("    Total pipeline:    %,.0f ms%n", t.pipelineMs());
                    out.printf("    Image rendering:   %,.0f ms (avg %.0f ms/page)%n",
                            t.totalImageExtractMs(), t.avgExtractPerPageMs());
                    out.printf("    OCR processing:    %,.0f ms (avg %.0f ms/page)%n",
                            t.totalOcrMs(), t.avgOcrPerPageMs());
                }
                out.println("─".repeat(60));

                if (result.pages() != null) {
                    for (var page : result.pages()) {
                        out.printf("%n── Page %d (%d words | render %.0f ms | OCR %.0f ms) ──%n",
                                page.page(), page.wordCount(), page.imageExtractMs(), page.ocrMs());
                        out.println(page.text());
                    }
                } else {
                    out.println(result.text());
                }
            }
        }
    }

    // ---------------------------------------------------------------
    // Pretty-print raw JSON string
    // ---------------------------------------------------------------

    public static String prettyJson(String rawJson) {
        var element = JsonParser.parseString(rawJson);
        return GSON.toJson(element);
    }

    // ---------------------------------------------------------------
    // Save text to file
    // ---------------------------------------------------------------

    public static void saveToFile(String text, Path path) throws IOException {
        Files.writeString(path, text);
    }
}
