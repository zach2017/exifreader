#!/bin/bash
# ──────────────────────────────────────────
#  OCR Extract — Start Script
# ──────────────────────────────────────────
set -e

echo "╔══════════════════════════════════════════════╗"
echo "║  Starting OCR Extract Stack...               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "This will:"
echo "  1. Build the custom Lambda image (with Tesseract)"
echo "  2. Start LocalStack"
echo "  3. Deploy the Lambda function"
echo "  4. Start the Flask backend"
echo "  5. Start the Nginx frontend"
echo ""

# Build and start everything
docker compose up --build

echo ""
echo "  Frontend → http://localhost:8080"
echo "  Backend  → http://localhost:5000/api/health"
