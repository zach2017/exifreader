# Lambda runtime image with Tesseract OCR
# LocalStack runs this as the Lambda container

FROM public.ecr.aws/lambda/provided:al2023

# Install Tesseract OCR + English language data
RUN dnf install -y tesseract tesseract-langpack-eng && \
    dnf clean all && \
    tesseract --version

# Copy the pre-built bootstrap binary
COPY dist/bootstrap ${LAMBDA_TASK_ROOT}/bootstrap
RUN chmod +x ${LAMBDA_TASK_ROOT}/bootstrap

ENTRYPOINT ["/lambda-entrypoint.sh"]
CMD ["bootstrap"]
