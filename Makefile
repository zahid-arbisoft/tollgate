.PHONY: dev test lint fmt build-web serve clean

dev:            ## Run gateway in dev mode
	uv run tollgate serve

test:           ## Run test suite
	uv run pytest -q

lint:           ## Ruff lint + format check
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt:            ## Autofix formatting
	uv run ruff format src tests
	uv run ruff check --fix src tests

build-web:      ## Build dashboard into src/tollgate/static
	cd web && npm ci && npm run build

clean:
	rm -rf .pytest_cache .ruff_cache dist build
