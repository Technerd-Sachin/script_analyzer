.PHONY: install check lint type dev api ui eval corpus trends

install:
	uv sync

lint:
	uv run ruff check src ui evals
	uv run ruff format --check src ui evals

type:
	uv run pyright

check: lint type

api:
	uv run bsa serve

ui:
	uv run streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true

dev:
	@echo "API on 127.0.0.1:8100, UI on 127.0.0.1:8501 (Ctrl+C stops both)"
	uv run bsa serve & uv run streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true; kill %1

eval:
	uv run bsa eval run

corpus:
	uv run bsa corpus build

trends:
	uv run bsa trends refresh
