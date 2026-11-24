PY ?= python3
VENV = .venv
BIN = $(VENV)/bin

.PHONY: setup api worker web build test dev

setup:            ## Instala dependências do backend e do frontend
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -r backend/requirements.txt
	cd frontend && npm install
	@test -f .env || cp .env.example .env

api:              ## API em http://localhost:8000 (docs em /api/docs)
	cd backend && ../$(BIN)/uvicorn app.main:app --reload --port 8000

worker:           ## Worker da fila (análise, renderização, monitoramento)
	cd backend && ../$(BIN)/python -m app.worker.main

web:              ## Frontend em modo desenvolvimento (http://localhost:5173)
	cd frontend && npm run dev

build:            ## Compila o frontend; a API passa a servi-lo em http://localhost:8000
	cd frontend && npm run build

test:             ## Testes do backend (inclui o pipeline completo com ffmpeg)
	cd backend && ../$(BIN)/python -m pytest -q
