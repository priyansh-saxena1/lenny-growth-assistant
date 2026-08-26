# Everything an evaluator needs. `make help` lists it.
.DEFAULT_GOAL := help
SHELL := /bin/bash

PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin
BACKEND := backend
TRANSCRIPTS_REPO := https://codeload.github.com/ChatPRD/lennys-podcast-transcripts/tar.gz/refs/heads/main

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ─── one-command paths ───────────────────────────────────────────────────────

.PHONY: up
up: .env ## Start the whole stack (Postgres + API + web) via Docker
	docker compose up --build -d
	@echo "waiting for the API…"
	@for i in $$(seq 1 60); do \
	  curl -fsS http://localhost:8000/api/health/live >/dev/null 2>&1 && break; \
	  sleep 2; done
	@echo ""
	@echo "  web    http://localhost:5173"
	@echo "  api    http://localhost:8000/docs"
	@echo "  health http://localhost:8000/api/health"
	@echo ""
	@echo "Index is empty until you run:  make ingest-docker"

.PHONY: down
down: ## Stop the stack
	docker compose down

.PHONY: clean
clean: ## Stop the stack and delete all data (database + vectors)
	docker compose down -v
	rm -rf .cache

.PHONY: logs
logs: ## Tail API logs
	docker compose logs -f api

.env: ## Create .env from the example if it doesn't exist
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

# ─── data ────────────────────────────────────────────────────────────────────

.PHONY: transcripts
transcripts: ## Download the transcript corpus (~9MB, 303 episodes)
	@if [ -d data/transcripts ] && [ -n "$$(ls -A data/transcripts 2>/dev/null)" ]; then \
	  echo "data/transcripts already populated ($$(ls data/transcripts | wc -l) episodes)"; \
	else \
	  mkdir -p data/transcripts .tmp; \
	  echo "downloading transcripts…"; \
	  curl -sL -o .tmp/lp.tgz $(TRANSCRIPTS_REPO); \
	  tar xzf .tmp/lp.tgz -C .tmp; \
	  cp -r .tmp/lennys-podcast-transcripts-main/episodes/* data/transcripts/; \
	  rm -rf .tmp; \
	  echo "got $$(ls data/transcripts | wc -l) episodes"; \
	fi

.PHONY: ingest-docker
ingest-docker: ## Ingest the corpus into the running stack
	docker compose exec api python -m app.cli ingest

.PHONY: ingest
ingest: $(VENV) transcripts ## Ingest locally (no Docker; uses the in-memory index)
	VECTOR_BACKEND=memory DATABASE_URL=sqlite+aiosqlite:///./local.sqlite3 \
	  PYTHONPATH=$(BACKEND) $(BIN)/python -m app.cli ingest

# ─── dev ─────────────────────────────────────────────────────────────────────

$(VENV): ## Create the virtualenv and install dependencies
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r $(BACKEND)/requirements-dev.txt
	@touch $(VENV)

.PHONY: install
install: $(VENV) ## Install backend dev dependencies
	@echo "installed"

.PHONY: dev
dev: $(VENV) ## Run the API locally with reload (needs Postgres, or set VECTOR_BACKEND=memory)
	cd $(BACKEND) && ../$(BIN)/uvicorn app.main:app --reload --port 8000

.PHONY: web
web: ## Run the frontend dev server
	cd frontend && npm install && npm run dev

.PHONY: test
test: $(VENV) ## Run the test suite (no database, no model, no network)
	cd $(BACKEND) && PYTHONPATH=. ../$(BIN)/python -m pytest tests -q

.PHONY: eval
eval: $(VENV) ## Retrieval + calibration eval, writes backend/eval/REPORT.md
	cd $(BACKEND) && PYTHONPATH=. ../$(BIN)/python eval/run_eval.py \
	  $(if $(EVAL_PROVIDER),--provider $(EVAL_PROVIDER),)

.PHONY: eval-ollama
eval-ollama: ## Full eval including answer quality against local Ollama
	$(MAKE) eval EVAL_PROVIDER=ollama

.PHONY: smoke
smoke: ## Hit a running API end to end and print the result
	@bash scripts/smoke.sh
