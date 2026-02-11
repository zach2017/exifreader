package com.ocr;

import com.ocr.util.FileUtils;
import com.ocr.util.FileUtils.FileType;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;

import static org.junit.jupiter.api.Assertions.*;

class FileUtilsTest {

    @TempDir
    Path tempDir;

    // ── detectType ──────────────────────────────────────────────

    @ParameterizedTest
    @CsvSource({
            "photo.png,   IMAGE",
            "scan.jpg,    IMAGE",
            "scan.jpeg,   IMAGE",
            "doc.tiff,    IMAGE",
            "doc.tif,     IMAGE",
            "icon.bmp,    IMAGE",
            "anim.gif,    IMAGE",
            "pic.webp,    IMAGE",
            "report.pdf,  PDF",
            "REPORT.PDF,  PDF",
            "Photo.PNG,   IMAGE",
    })
    void detectType_recognizesExtensions(String filename, FileType expected) {
        assertEquals(expected, FileUtils.detectType(Path.of(filename)));
    }

    @ParameterizedTest
    @ValueSource(strings = {"readme.txt", "data.csv", "noext", "archive.zip"})
    void detectType_unknownExtensions(String filename) {
        assertEquals(FileType.UNKNOWN, FileUtils.detectType(Path.of(filename)));
    }

    // ── readAsBase64 ────────────────────────────────────────────

    @Test
    void readAsBase64_encodesFileCorrectly() throws IOException {
        byte[] content = "Hello OCR World".getBytes();
        Path file = tempDir.resolve("test.txt");
        Files.write(file, content);

        String b64 = FileUtils.readAsBase64(file);

        byte[] decoded = Base64.getDecoder().decode(b64);
        assertArrayEquals(content, decoded);
    }

    @Test
    void readAsBase64_rejectsTooLargeFile() throws IOException {
        Path file = tempDir.resolve("big.bin");
        // Create a file just over 1 MB
        byte[] data = new byte[1024 * 1024 + 1];
        Files.write(file, data);

        assertThrows(IllegalArgumentException.class,
                () -> FileUtils.readAsBase64(file, 1));
    }

    @Test
    void readAsBase64_acceptsFileUnderLimit() throws IOException {
        Path file = tempDir.resolve("small.bin");
        Files.write(file, new byte[100]);

        assertDoesNotThrow(() -> FileUtils.readAsBase64(file, 1));
    }

    // ── formatSize ──────────────────────────────────────────────

    @Test
    void formatSize_bytes() {
        assertEquals("512 B", FileUtils.formatSize(512));
    }

    @Test
    void formatSize_kilobytes() {
        String result = FileUtils.formatSize(2048);
        assertTrue(result.contains("KB"));
    }

    @Test
    void formatSize_megabytes() {
        String result = FileUtils.formatSize(5 * 1024 * 1024);
        assertTrue(result.contains("MB"));
    }
}
