.PHONY: setup lint test

setup:
	uv sync --locked

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy

test:
	uv run pytest -m "not db and not perf"
