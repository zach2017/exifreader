#!/bin/bash
###############################################################################
# DocProc — Quick Setup Script
# Run this to start the entire system locally
###############################################################################

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║  DocProc — Document Processing Pipeline      ║"
echo "║  Setting up local development environment    ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is required but not installed."
    echo "   Install from: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is required but not installed."
    exit 1
fi

echo "▸ Starting services..."
docker-compose up -d

echo ""
echo "▸ Waiting for LocalStack to initialize..."
for i in {1..60}; do
    if curl -sf http://localhost:4566/_localstack/health | grep -q '"s3"' 2>/dev/null; then
        echo "  ✓ LocalStack is healthy"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "  ⚠ LocalStack took too long to start. Check: docker-compose logs localstack"
        exit 1
    fi
    sleep 2
done

echo ""
echo "▸ Waiting for Elasticsearch..."
for i in {1..30}; do
    if curl -sf http://localhost:9200/_cluster/health 2>/dev/null | grep -q '"status"'; then
        echo "  ✓ Elasticsearch is healthy"
        break
    fi
    sleep 2
done

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ DocProc is ready!                        ║"
echo "║                                              ║"
echo "║  Frontend:       http://localhost:8080        ║"
echo "║  LocalStack:     http://localhost:4566        ║"
echo "║  Elasticsearch:  http://localhost:9200        ║"
echo "║                                              ║"
echo "║  Upload a file and watch the magic happen!   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  Useful commands:"
echo "    docker-compose logs -f localstack     # View LocalStack logs"
echo "    docker-compose logs -f elasticsearch  # View ES logs"
echo "    docker-compose down -v                # Stop and clean up"
echo ""
