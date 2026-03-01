.PHONY: build up down test test-go test-e2e logs clean

# 1) Build the Lambda binary
build:
	mkdir -p lambda/dist
	docker compose build lambda-builder
	docker compose run --rm lambda-builder

# 2) Start services (build Lambda first, then LocalStack runs setup-aws.sh automatically)
up: build
	docker compose up -d localstack web
	@echo "Waiting for LocalStack setup..."
	@sleep 5
	@docker compose logs localstack 2>&1 | grep -q "Setup complete" && echo "✅ Ready at http://localhost:8080" || echo "⏳ Still initializing — check: docker compose logs -f localstack"

down:
	docker compose down -v --remove-orphans

# Go unit tests
test-go:
	docker run --rm -v $$(pwd)/lambda:/app -w /app golang:1.22 sh -c "go mod tidy && go test -v -count=1 ./..."

# Playwright E2E tests
test-e2e:
	docker compose --profile test run --rm tests

test: test-go test-e2e

logs:
	docker compose logs -f localstack

clean:
	docker compose down -v --remove-orphans --rmi local
	rm -rf lambda/dist test-results test-images/*.png test-images/*.jpg
