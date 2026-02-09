FROM python:3.9-slim
RUN apt-get update -qq && \
    apt-get install -y -qq curl zip unzip && \
    pip install --no-cache-dir awscli && \
    rm -rf /var/lib/apt/lists/*
COPY deploy.sh /deploy.sh
RUN chmod +x /deploy.sh
CMD ["/bin/bash", "/deploy.sh"]
