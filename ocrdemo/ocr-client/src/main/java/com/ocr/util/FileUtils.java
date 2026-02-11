package com.ocr.util;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.Set;

/**
 * File utilities for reading, encoding, and validating input files.
 */
public final class FileUtils {

    private FileUtils() {}

    private static final Set<String> IMAGE_EXTENSIONS = Set.of(
            ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp"
    );

    private static final Set<String> PDF_EXTENSIONS = Set.of(".pdf");

    /** Supported file type categories. */
    public enum FileType { IMAGE, PDF, UNKNOWN }

    /**
     * Detect file type from extension.
     */
    public static FileType detectType(Path file) {
        String name = file.getFileName().toString().toLowerCase();
        int dot = name.lastIndexOf('.');
        if (dot < 0) return FileType.UNKNOWN;

        String ext = name.substring(dot);
        if (IMAGE_EXTENSIONS.contains(ext)) return FileType.IMAGE;
        if (PDF_EXTENSIONS.contains(ext))   return FileType.PDF;
        return FileType.UNKNOWN;
    }

    /**
     * Read a file and return its contents as a base64-encoded string.
     *
     * @throws IOException if the file cannot be read
     * @throws IllegalArgumentException if the file exceeds maxSizeMb
     */
    public static String readAsBase64(Path file, int maxSizeMb) throws IOException {
        long sizeBytes = Files.size(file);
        long maxBytes = (long) maxSizeMb * 1024 * 1024;

        if (sizeBytes > maxBytes) {
            throw new IllegalArgumentException(
                    "File %s is %.1f MB, exceeds %d MB limit".formatted(
                            file.getFileName(), sizeBytes / (1024.0 * 1024.0), maxSizeMb
                    )
            );
        }

        byte[] bytes = Files.readAllBytes(file);
        return Base64.getEncoder().encodeToString(bytes);
    }

    /**
     * Read with default 10 MB limit.
     */
    public static String readAsBase64(Path file) throws IOException {
        return readAsBase64(file, 10);
    }

    /**
     * Format byte count for display (e.g. "2.4 MB").
     */
    public static String formatSize(long bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return "%.1f KB".formatted(bytes / 1024.0);
        return "%.1f MB".formatted(bytes / (1024.0 * 1024.0));
    }
}
