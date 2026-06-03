.PHONY: run run-bg worker worker-bg stop migrate migrate-new migrate-down test lint install

PID_DIR := ../.dev
API_PID := $(PID_DIR)/api.pid
WORKER_PID := $(PID_DIR)/worker.pid

install:
	uv sync

run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run-bg:
	@mkdir -p $(PID_DIR)
	@if [ -f $(API_PID) ] && kill -0 $$(cat $(API_PID)) 2>/dev/null; then echo "API already running"; else \
		nohup uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > $(PID_DIR)/api.log 2>&1 & echo $$! > $(API_PID); \
		echo "API started (pid $$(cat $(API_PID)))"; fi

worker:
	uv run python -m app.workers.run_worker

worker-bg:
	@mkdir -p $(PID_DIR)
	@if [ -f $(WORKER_PID) ] && kill -0 $$(cat $(WORKER_PID)) 2>/dev/null; then echo "Worker already running"; else \
		nohup uv run python -m app.workers.run_worker > $(PID_DIR)/worker.log 2>&1 & echo $$! > $(WORKER_PID); \
		echo "Worker started (pid $$(cat $(WORKER_PID)))"; fi

stop:
	@if [ -f $(API_PID) ]; then kill $$(cat $(API_PID)) 2>/dev/null || true; rm -f $(API_PID); echo "API stopped"; fi
	@if [ -f $(WORKER_PID) ]; then kill $$(cat $(WORKER_PID)) 2>/dev/null || true; rm -f $(WORKER_PID); echo "Worker stopped"; fi
	@lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true

migrate:
	uv run alembic upgrade head

migrate-new:
	uv run alembic revision --autogenerate -m "$(name)"

migrate-down:
	uv run alembic downgrade -1

test:
	uv run pytest -q

lint:
	uv run ruff check app tests
