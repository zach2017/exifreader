package com.ocr.client;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.ocr.model.OcrRequest;
import com.ocr.model.OcrResponse.*;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.DefaultCredentialsProvider;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.SdkBytes;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.lambda.LambdaClient;
import software.amazon.awssdk.services.lambda.model.InvokeRequest;
import software.amazon.awssdk.services.lambda.model.InvokeResponse;

import java.nio.charset.StandardCharsets;

/**
 * Service that invokes the OCR Lambda functions via the AWS SDK.
 *
 * <p>Uses Java 21 pattern matching switch to dispatch each
 * {@link OcrRequest} variant to the correct Lambda function and
 * deserialize its response.</p>
 */
public class LambdaInvoker implements AutoCloseable {

    private static final Gson GSON = new GsonBuilder()
            .setPrettyPrinting()
            .create();

    private final LambdaClient lambda;
    private final String imageOcrFunction;
    private final String pdfExtractFunction;
    private final String pdfOcrFunction;

    /**
     * @param region              AWS region (e.g. "us-east-1")
     * @param imageOcrFunction    name/ARN of the image OCR Lambda
     * @param pdfExtractFunction  name/ARN of the PDF text extraction Lambda
     * @param pdfOcrFunction      name/ARN of the PDF OCR Lambda
     */
    public LambdaInvoker(String region,
                         String imageOcrFunction,
                         String pdfExtractFunction,
                         String pdfOcrFunction) {
        this(region, null, imageOcrFunction, pdfExtractFunction, pdfOcrFunction);
    }

    /**
     * @param region              AWS region
     * @param endpointOverride    optional endpoint URL (e.g. "http://localhost:7878" for LocalStack)
     * @param imageOcrFunction    name/ARN of the image OCR Lambda
     * @param pdfExtractFunction  name/ARN of the PDF text extraction Lambda
     * @param pdfOcrFunction      name/ARN of the PDF OCR Lambda
     */
    public LambdaInvoker(String region,
                         String endpointOverride,
                         String imageOcrFunction,
                         String pdfExtractFunction,
                         String pdfOcrFunction) {
        var builder = LambdaClient.builder()
                .region(Region.of(region));

        if (endpointOverride != null && !endpointOverride.isBlank()) {
            // Custom endpoint (e.g. LocalStack) — use static dummy credentials
            // to prevent the SDK from making background STS/IMDS calls that
            // would fail with UnknownHostException
            builder.endpointOverride(java.net.URI.create(endpointOverride))
                   .credentialsProvider(StaticCredentialsProvider.create(
                           AwsBasicCredentials.create("test", "test")
                   ));
        } else {
            // Real AWS — use the default credential chain
            builder.credentialsProvider(DefaultCredentialsProvider.create());
        }

        this.lambda = builder.build();
        this.imageOcrFunction = imageOcrFunction;
        this.pdfExtractFunction = pdfExtractFunction;
        this.pdfOcrFunction = pdfOcrFunction;
    }

    /** Constructor for testing – accepts a pre-built LambdaClient. */
    LambdaInvoker(LambdaClient lambda,
                  String imageOcrFunction,
                  String pdfExtractFunction,
                  String pdfOcrFunction) {
        this.lambda = lambda;
        this.imageOcrFunction = imageOcrFunction;
        this.pdfExtractFunction = pdfExtractFunction;
        this.pdfOcrFunction = pdfOcrFunction;
    }

    // ---------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------

    /**
     * Invoke the appropriate Lambda based on the request type.
     * Uses an exhaustive pattern-matching switch (Java 21).
     *
     * @return raw JSON response string from the Lambda
     */
    public String invokeRaw(OcrRequest request) {
        return switch (request) {
            case OcrRequest.ImageOcr img   -> invoke(imageOcrFunction, buildImagePayload(img));
            case OcrRequest.PdfExtract pdf -> invoke(pdfExtractFunction, buildPdfExtractPayload(pdf));
            case OcrRequest.PdfOcr ocr     -> invoke(pdfOcrFunction, buildPdfOcrPayload(ocr));
        };
    }

    /** Invoke and deserialize to the typed response record. */
    public ImageOcrResult invokeImageOcr(OcrRequest.ImageOcr request) {
        String json = invoke(imageOcrFunction, buildImagePayload(request));
        return GSON.fromJson(json, ImageOcrResult.class);
    }

    public PdfExtractResult invokePdfExtract(OcrRequest.PdfExtract request) {
        String json = invoke(pdfExtractFunction, buildPdfExtractPayload(request));
        return GSON.fromJson(json, PdfExtractResult.class);
    }

    public PdfOcrResult invokePdfOcr(OcrRequest.PdfOcr request) {
        String json = invoke(pdfOcrFunction, buildPdfOcrPayload(request));
        return GSON.fromJson(json, PdfOcrResult.class);
    }

    // ---------------------------------------------------------------
    // Payload builders
    // ---------------------------------------------------------------

    public static String buildImagePayload(OcrRequest.ImageOcr req) {
        var obj = new JsonObject();
        obj.addProperty("image", req.image());
        obj.addProperty("filename", req.filename());
        return GSON.toJson(obj);
    }

    public static String buildPdfExtractPayload(OcrRequest.PdfExtract req) {
        var obj = new JsonObject();
        obj.addProperty("pdf", req.pdf());
        obj.addProperty("filename", req.filename());
        return GSON.toJson(obj);
    }

    public static String buildPdfOcrPayload(OcrRequest.PdfOcr req) {
        var obj = new JsonObject();
        obj.addProperty("pdf", req.pdf());
        obj.addProperty("filename", req.filename());
        obj.addProperty("dpi", req.dpi());
        return GSON.toJson(obj);
    }

    // ---------------------------------------------------------------
    // Core Lambda invocation
    // ---------------------------------------------------------------

    private String invoke(String functionName, String payload) {
        InvokeRequest invokeReq = InvokeRequest.builder()
                .functionName(functionName)
                .payload(SdkBytes.fromString(payload, StandardCharsets.UTF_8))
                .build();

        InvokeResponse response = lambda.invoke(invokeReq);

        // Check for Lambda-level errors (not application errors inside the response)
        if (response.functionError() != null && !response.functionError().isEmpty()) {
            throw new LambdaInvocationException(
                    "Lambda function error (%s): %s".formatted(
                            response.functionError(),
                            response.payload().asUtf8String()
                    )
            );
        }

        return response.payload().asUtf8String();
    }

    @Override
    public void close() {
        lambda.close();
    }

    // ---------------------------------------------------------------
    // Custom exception
    // ---------------------------------------------------------------

    public static class LambdaInvocationException extends RuntimeException {
        public LambdaInvocationException(String message) { super(message); }
        public LambdaInvocationException(String message, Throwable cause) { super(message, cause); }
    }
}
