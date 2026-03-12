.PHONY: install dev test test-cov lint package-check ci clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=open_researcher --cov-report=term-missing --cov-fail-under=75

lint:
	ruff check src/ tests/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

package-check:
	python -m pip install --upgrade pip build
	python -m build
	python -m pip install --force-reinstall dist/*.whl
	open-researcher --help > /dev/null

ci:
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) test-cov
	$(MAKE) package-check

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
