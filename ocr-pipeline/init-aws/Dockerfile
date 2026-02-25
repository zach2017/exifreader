FROM debian:bookworm-slim

# ── Install AWS CLI v2 from official installer ──
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        unzip \
        ca-certificates \
        jq \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip \
    && apt-get purge -y unzip \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify AWS CLI v2
RUN aws --version

COPY init.sh /opt/init.sh
RUN chmod +x /opt/init.sh

ENTRYPOINT ["/bin/bash"]
CMD ["/opt/init.sh"]
