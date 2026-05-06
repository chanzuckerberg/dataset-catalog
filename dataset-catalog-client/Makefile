.PHONY: help init test lint format typecheck check clean build pre-commit

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  init        Install all dependencies and set up pre-commit hooks"
	@echo "  test        Run tests"
	@echo "  lint        Lint with ruff (auto-fix)"
	@echo "  format      Format with ruff"
	@echo "  typecheck   Type-check with mypy"
	@echo "  check       Run lint + format + typecheck + tests"
	@echo "  pre-commit  Run all pre-commit hooks on all files"
	@echo "  build       Build the Python package"
	@echo "  clean       Remove build artifacts and cache files"

init:
	uv sync --all-groups
	cd .. && uv run pre-commit install

test:
	uv run pytest

lint:
	uv run ruff check --fix .

format:
	uv run ruff format .

typecheck:
	uv run mypy catalog_client

check: lint format typecheck test

pre-commit:
	cd .. && uv run pre-commit run --all-files

build: clean
	uv build

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "dist" -exec rm -rf {} +
