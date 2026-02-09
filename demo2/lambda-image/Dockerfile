# Extends official AWS Lambda Python 3.11 image with Tesseract + Poppler.
# LocalStack 3.x uses this via LAMBDA_RUNTIME_IMAGE_MAPPING so the
# Lambda handler can call Tesseract for OCR.
# The handler.py + Python deps are deployed via zip — this only adds system binaries.
FROM public.ecr.aws/lambda/python:3.11

RUN dnf install -y \
        tesseract \
        poppler-utils \
    && dnf clean all \
    && tesseract --version
