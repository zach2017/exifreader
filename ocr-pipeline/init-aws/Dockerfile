FROM debian:bookworm-slim

# ── Install AWS CLI v2 from official installer + utilities ──
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        unzip \
        zip \
        ca-certificates \
        jq \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify
RUN aws --version && zip --version | head -1

COPY init.sh /opt/init.sh
RUN chmod +x /opt/init.sh

ENTRYPOINT ["/bin/bash"]
CMD ["/opt/init.sh"]
