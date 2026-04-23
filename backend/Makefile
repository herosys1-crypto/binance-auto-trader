.PHONY: install run test lint migrate upgrade downgrade seed-templates worker-keepalive worker-reconcile worker-tpsl worker-symbol-sync scheduler telegram-test user-stream pg-test

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -q

lint:
	python -m compileall app

migrate:
	alembic revision --autogenerate -m "auto migration"

upgrade:
	alembic upgrade head

downgrade:
	alembic downgrade -1

seed-templates:
	psql $$DATABASE_URL -f seed_strategy_templates.sql

worker-keepalive:
	python -m app.workers.run_workers --worker keepalive

worker-reconcile:
	python -m app.workers.run_workers --worker reconcile

worker-tpsl:
	python -m app.workers.run_workers --worker tp-sl

worker-symbol-sync:
	python -m app.workers.run_workers --worker symbol-sync

scheduler:
	python -m app.workers.scheduler_runner

telegram-test:
	curl -X POST http://127.0.0.1:8000/api/v1/admin/test-telegram -H "Authorization: Bearer $$TOKEN"

user-stream:
	python -m app.workers.run_user_stream

pg-test:
	TEST_DATABASE_URL=$$TEST_DATABASE_URL pytest -q tests/integration
