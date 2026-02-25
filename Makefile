SHELL := /bin/bash
.DEFAULT_GOAL := help

PROJECT_ROOT := $(CURDIR)
ENV_FILE := $(PROJECT_ROOT)/.env
API_DIR := $(PROJECT_ROOT)/services/api
MOBILE_DIR := $(PROJECT_ROOT)/apps/mobile
INFRA_DIR := $(PROJECT_ROOT)/infra

ifeq (,$(wildcard $(ENV_FILE)))
$(warning No existe .env en la raiz. Ejecuta: make env)
endif

.PHONY: help env check-tools setup up down reset-db logs ps \
	api-install api-migrate api-run api-dev api-test api-lint api-health \
	mobile-install mobile-start mobile-devclient ios-dev-build

help:
	@echo "Comandos principales:"
	@echo "  make env            # Crea .env desde .env.example"
	@echo "  make setup          # Infra + deps API + deps mobile + migraciones"
	@echo "  make up             # Levanta solo Postgres"
	@echo "  make api-dev        # Instala deps, migra y arranca API"
	@echo "  make mobile-start   # Arranca Expo"
	@echo "  make mobile-devclient # Arranca Expo para Development Build"
	@echo "  make ios-dev-build  # Lanza EAS build iOS development client"
	@echo "  make down           # Baja Postgres"
	@echo "  make reset-db       # Reinicia Postgres borrando volumen"
	@echo "  make logs           # Logs de Postgres"
	@echo "  make api-test       # Pytest backend"
	@echo "  make api-lint       # Ruff backend"

env:
	@if [ ! -f "$(ENV_FILE)" ]; then \
		cp "$(PROJECT_ROOT)/.env.example" "$(ENV_FILE)"; \
		echo "Creado $(ENV_FILE)"; \
	else \
		echo "$(ENV_FILE) ya existe"; \
	fi

check-tools:
	@command -v docker >/dev/null || (echo "Falta docker" && exit 1)
	@command -v python3 >/dev/null || (echo "Falta python3" && exit 1)
	@command -v npm >/dev/null || (echo "Falta npm" && exit 1)

setup: env up api-install api-migrate mobile-install
	@echo "Setup listo."

up: env
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" up -d
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" ps

down:
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" down

reset-db:
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" down -v
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" up -d
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" ps

logs:
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" logs -f postgres

ps:
	@cd "$(INFRA_DIR)" && docker compose --env-file "$(ENV_FILE)" ps

api-install:
	@cd "$(API_DIR)" && python3 -m pip install --break-system-packages -e '.[dev]'

api-migrate:
	@cd "$(API_DIR)" && set -a && source "$(ENV_FILE)" && set +a && python3 -m alembic upgrade head

api-run:
	@cd "$(API_DIR)" && set -a && source "$(ENV_FILE)" && set +a && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $$API_PORT --reload

api-dev: api-install api-migrate api-run

api-test:
	@cd "$(API_DIR)" && python3 -m pytest -q

api-lint:
	@cd "$(API_DIR)" && python3 -m ruff check .

api-health:
	@curl -sS http://localhost:8000/health || true

mobile-install:
	@cd "$(MOBILE_DIR)" && npm install

mobile-start: mobile-install
	@cd "$(MOBILE_DIR)" && [ -f .env ] || cp .env.example .env
	@cd "$(MOBILE_DIR)" && npm run start

mobile-devclient: mobile-install
	@cd "$(MOBILE_DIR)" && [ -f .env ] || cp .env.example .env
	@cd "$(MOBILE_DIR)" && npm run devclient:start

ios-dev-build: mobile-install
	@cd "$(MOBILE_DIR)" && npm run eas:build:ios:dev
