.PHONY: env-create install dev run-server run-web clean init-data db-prepare db-verify db-adopt db-downgrade db-current db-history neo4j-dietary-sync monitoring-up monitoring-down eval-prepare eval-run eval-regression docker-build docker-up docker-down help

env-create:
	conda env create -f environment.yml
	conda run -n safemeal_env python -m pip install --require-hashes -r requirements.lock

install:
	python -m pip install --require-hashes -r requirements.lock
	cd web && npm ci

dev:
	$(MAKE) -j 2 run-server run-web

run-server:
	python -m uvicorn back.main:application --host 0.0.0.0 --port 8000

run-web:
	cd web && npm run dev

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf dist/ build/ *.egg-info web/dist web/node_modules

init-data:
	mkdir -p data/mysql data/milvus data/lightrag data/runtime uploads

db-prepare:
	python -m back.infrastructure.persistence.migration_gate upgrade

db-verify:
	python -m back.infrastructure.persistence.migration_gate verify

db-adopt:
	python -m back.infrastructure.persistence.migration_gate adopt --backup-file "$(backup_file)" --backup-sha256 "$(backup_sha256)"

db-downgrade:
	alembic downgrade -1

db-current:
	alembic current

db-history:
	alembic history --verbose

neo4j-dietary-sync:
	python -m back.infrastructure.retrieval.neo4j.dietary_migration

monitoring-up:
	docker compose --profile monitoring up -d --wait api alert-receiver alertmanager prometheus grafana

monitoring-down:
	docker compose --profile monitoring stop grafana prometheus alertmanager alert-receiver

eval-prepare:
	python -m back.evaluation prepare --target both

eval-run:
	python -m back.evaluation run --enforce-gates --output evaluation_results/latest.json --progress evaluation_results/latest.progress.jsonl

eval-regression:
	python -m back.evaluation regression --baseline "$(baseline)" --candidate "$(candidate)" --output evaluation_results/regression-latest.json

docker-build:
	docker compose build

docker-up:
	docker compose up -d --wait

docker-down:
	docker compose down

help:
	@echo "SafeMeal Agent runtime commands"
	@echo "make env-create    - create the Python 3.11 runtime environment"
	@echo "make install       - install locked backend and frontend dependencies"
	@echo "make dev           - run backend and frontend"
	@echo "make db-prepare    - migrate and verify the database"
	@echo "make db-verify     - verify database revision and required data"
	@echo "make db-adopt backup_file=/abs/backup.sql backup_sha256=<sha256>"
	@echo "make neo4j-dietary-sync - repair and verify structured dietary data"
	@echo "make monitoring-up - start Prometheus, Alertmanager, receiver and Grafana"
	@echo "make eval-run      - run all frozen cases with Judge and enforce gates"
	@echo "make docker-build  - build runtime images"
	@echo "make docker-up     - start the runtime stack"
	@echo "make docker-down   - stop the runtime stack"
