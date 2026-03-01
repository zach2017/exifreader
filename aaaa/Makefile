.PHONY: up down build test test-go test-e2e logs clean setup

# Start all services
up: build
	docker compose up -d
	@echo "Waiting for setup to complete..."
	docker compose logs -f setup
	@echo ""
	@echo "✅ Services running! Open http://localhost:8080"

# Build all images
build:
	docker compose build

# Stop all services
down:
	docker compose down -v --remove-orphans

# Run Go unit tests (inside Docker)
test-go:
	docker run --rm -v $(PWD)/lambda:/app -w /app golang:1.22 sh -c "go mod tidy && go test -v ./..."

# Run Playwright E2E tests
test-e2e:
	docker compose run --rm tests

# Run all tests
test: test-go test-e2e

# View logs
logs:
	docker compose logs -f

# View specific service logs
logs-%:
	docker compose logs -f $*

# Clean everything
clean:
	docker compose down -v --remove-orphans --rmi local
	rm -rf test-results test-images/*.png test-images/*.jpg localstack-data

# Setup only (rebuild resources)
setup:
	docker compose up -d localstack
	docker compose run --rm setup
