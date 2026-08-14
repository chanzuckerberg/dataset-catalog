.PHONY: help init test lint format typecheck check clean pre-commit eval eval-full eval-aws eval-golden

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  init        Install all dependencies and set up pre-commit hooks"
	@echo "  test        Run tests"
	@echo "  eval        Run the checksum eval, fast tier (see evals/README.md)"
	@echo "  eval-full   Run the checksum eval including 256MB/1GB cases"
	@echo "  eval-aws    Run the checksum eval against real S3 (needs CATALOG_EVAL_S3_BUCKET)"
	@echo "  eval-golden Re-pin the checksum eval's golden vectors, then review the diff"
	@echo "  lint        Lint with ruff (auto-fix)"
	@echo "  format      Format with ruff"
	@echo "  typecheck   Type-check with mypy"
	@echo "  check       Run lint + format + typecheck + tests"
	@echo "  pre-commit  Run all pre-commit hooks on all files"
	@echo "  clean       Remove build artifacts and cache files"

init:
	uv sync --all-groups
	cd .. && uv run pre-commit install

test:
	uv run pytest

eval:
	uv run python -m evals.checksum

eval-full:
	uv run python -m evals.checksum --tier full

eval-aws:
	uv run python -m evals.checksum --tier aws

# Full tier too, so the 256MB-boundary vectors are re-pinned along with the rest.
eval-golden:
	uv run python -m evals.checksum --tier full --update-golden

lint:
	uv run ruff check --fix .

format:
	uv run ruff format .

typecheck:
	uv run mypy catalog_client

check: lint format typecheck test

pre-commit:
	cd .. && uv run pre-commit run --all-files

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "dist" -exec rm -rf {} +
