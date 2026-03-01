FROM mcr.microsoft.com/playwright:v1.48.0-noble

# Install AWS CLI and ImageMagick for test helpers
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        awscli \
        imagemagick \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Fix ImageMagick policy to allow text rendering
RUN sed -i 's/<policy domain="path" rights="none" pattern="@\*"/<policy domain="path" rights="read|write" pattern="@*"/' /etc/ImageMagick-6/policy.xml 2>/dev/null || true

WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install
RUN npx playwright install --with-deps chromium

# Copy test files
COPY . .

# Create test output dir
RUN mkdir -p /app/test-results /app/test-images

# Run tests
CMD ["npx", "playwright", "test", "--reporter=list"]
