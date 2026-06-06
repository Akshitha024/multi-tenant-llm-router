.PHONY: help install lint typecheck test serve bench plots clean

PORT ?= 8765
ADAPTERS ?= 10
RPS ?= 5

help:
	@echo "make install                       - deps"
	@echo "make lint / typecheck / test       - quality gates"
	@echo "make serve PORT=8765               - run the FastAPI router (mock backend by default)"
	@echo "make bench ADAPTERS=10 RPS=5       - synthetic load against the running router"
	@echo "make plots                         - regenerate the chart set"

install: ; uv sync --all-extras
lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
typecheck: ; uv run mypy src
test: ; uv run pytest -m "not slow"
serve: ; uv run router serve --port $(PORT)
bench: ; uv run router bench --adapters $(ADAPTERS) --rps $(RPS)
plots: ; uv run router plots --out-dir results/figures
clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
