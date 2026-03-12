.PHONY: install dev test lint clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
