FROM public.ecr.aws/lambda/python:3.12

# Install tesseract and dependencies
RUN dnf install -y tesseract tesseract-langpack-eng && \
    dnf clean all

COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
