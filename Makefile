.PHONY: install run-server lint format-check typecheck test check init-data db-upgrade neo4j-sync eval-prepare eval-run docker-up docker-down docker-smoke help

install:
	python -m pip install -r requirements.txt

run-server:
	python -m uvicorn safemeal.main:application --host 0.0.0.0 --port 8000 --reload

lint:
	python -m ruff check safemeal tests

format-check:
	python -m ruff format --check safemeal tests

typecheck:
	python -m mypy safemeal

test:
	PYTHONPATH=. python -m pytest -q

check: lint format-check typecheck test

init-data:
	mkdir -p data/runtime uploads

db-upgrade:
	alembic upgrade head

neo4j-sync:
	python -m safemeal.infrastructure.retrieval.neo4j.dietary_migration

eval-prepare:
	python -m safemeal.evaluation prepare --target milvus

eval-run:
	python -m safemeal.evaluation run --output evaluation_results/latest.json

docker-up:
	docker compose up -d --wait

docker-down:
	docker compose down

docker-smoke:
	docker compose config --quiet
	docker build -t safemeal:smoke .

help:
	@echo "make install       - install backend dependencies"
	@echo "make run-server    - start the local API"
	@echo "make check         - run lint, type checking and tests"
	@echo "make db-upgrade    - apply Alembic migrations"
	@echo "make neo4j-sync    - import the domain recipe graph"
	@echo "make eval-prepare  - index the frozen corpus in Milvus"
	@echo "make eval-run      - run metrics and LLM Judge evaluation"
	@echo "make docker-up     - start the complete local stack"
	@echo "make docker-down   - stop the local stack"
