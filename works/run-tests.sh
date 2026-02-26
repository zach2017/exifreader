#!/usr/bin/env bash
set -e

echo "══════════════════════════════════════════"
echo "  OCR Solution — Test Runner"
echo "══════════════════════════════════════════"
echo ""

MODE="${1:-unit}"

case "$MODE" in
    unit)
        echo "▶ Running unit tests (S3 + Lambda — no Postgres needed)"
        echo ""
        PYTHONPATH=api-server:lambda:$PYTHONPATH \
            python -m pytest tests/test_s3.py tests/test_lambda.py -v --tb=short
        ;;
    all)
        echo "▶ Running ALL tests via Docker Compose (includes Postgres)"
        echo ""
        docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test-runner
        docker compose -f docker-compose.test.yml down -v
        ;;
    *)
        echo "Usage: $0 [unit|all]"
        echo "  unit  — S3 + Lambda tests only (default, no Docker needed)"
        echo "  all   — Full suite in Docker with Postgres"
        exit 1
        ;;
esac
