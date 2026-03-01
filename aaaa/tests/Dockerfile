FROM mcr.microsoft.com/playwright:v1.48.0-noble

RUN apt-get update && \
    apt-get install -y --no-install-recommends imagemagick fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

# Fix ImageMagick policy
RUN if [ -f /etc/ImageMagick-6/policy.xml ]; then \
      sed -i 's/<policy domain="path" rights="none"/<policy domain="path" rights="read|write"/' /etc/ImageMagick-6/policy.xml; \
    fi

WORKDIR /app
COPY package.json ./
RUN npm install && npx playwright install --with-deps chromium
COPY . .
RUN mkdir -p /app/test-results /app/test-images

CMD ["npx", "playwright", "test", "--reporter=list"]
