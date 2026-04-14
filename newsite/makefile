# =============================================================================
# Makefile for Django LLM
# Usage: make <command>
# =============================================================================

.PHONY: run dev test pytest fastapi migrate static certs nginx superuser shell clean logs help
.PHONY: install lint format audit health backup restore docker ports env-check

# Color output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# Environment check
PYTHON := python3
PIP := pip3
DJANGO_SETTINGS := newsite.settings

# -------------------------
# Environment & Validation
# -------------------------

env-check:
    @echo "$(BLUE)Checking environment...$(NC)"
    @command -v $(PYTHON) >/dev/null 2>&1 || { echo "$(RED)Python3 not found$(NC)"; exit 1; }
    @command -v $(PIP) >/dev/null 2>&1 || { echo "$(RED)Pip3 not found$(NC)"; exit 1; }
    @[ -f requirements.txt ] || { echo "$(RED)requirements.txt not found$(NC)"; exit 1; }
    @[ -f manage.py ] || { echo "$(RED)manage.py not found$(NC)"; exit 1; }
    @echo "$(GREEN)✓ Environment check passed$(NC)"

ports-check:
    @echo "$(BLUE)Checking required ports...$(NC)"
    @lsof -i :8000 >/dev/null 2>&1 && echo "$(YELLOW)⚠ Port 8000 in use$(NC)" || echo "$(GREEN)✓ Port 8000 available$(NC)"
    @lsof -i :8001 >/dev/null 2>&1 && echo "$(YELLOW)⚠ Port 8001 in use$(NC)" || echo "$(GREEN)✓ Port 8001 available$(NC)"
    @lsof -i :443 >/dev/null 2>&1 && echo "$(YELLOW)⚠ Port 443 in use$(NC)" || echo "$(GREEN)✓ Port 443 available$(NC)"

# -------------------------
# Running
# -------------------------

run: env-check ports-check
    @echo "$(BLUE)Starting full stack...$(NC)"
    @chmod +x start.sh && ./start.sh

dev: env-check
    @echo "$(BLUE)Starting Django development server...$(NC)"
    @ollama serve & $(PYTHON) manage.py runserver

fastapi: env-check ports-check
    @echo "$(BLUE)Starting FastAPI development server...$(NC)"
    @uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8001 --reload

fastapi-gunicorn: env-check ports-check
    @echo "$(BLUE)Starting FastAPI with Gunicorn + Uvicorn workers...$(NC)"
    @$(PYTHON) -m gunicorn -c gunicorn_conf.py fastapi_app.main:app

dev-all: env-check ports-check
    @echo "$(BLUE)Starting Django + FastAPI in development mode...$(NC)"
    @ollama serve & \
    uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8001 --reload & \
    $(PYTHON) manage.py runserver
    @echo "$(GREEN)✓ All services started$(NC)"

gunicorn: env-check ports-check
    @echo "$(BLUE)Starting Gunicorn (Django)...$(NC)"
    @$(PYTHON) -m gunicorn --workers 3 --timeout 120 --bind 127.0.0.1:8000 --reload newsite.wsgi:application

uvicorn: env-check ports-check
    @echo "$(BLUE)Starting Uvicorn (FastAPI)...$(NC)"
    @uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8001 --workers 2

docker-fastapi: env-check
    @echo "$(BLUE)Starting FastAPI container with Docker socket access...$(NC)"
    @cd .. && docker-compose up --build fastapi

# -------------------------
# Testing
# -------------------------

test: env-check
    @echo "$(BLUE)Running Django tests...$(NC)"
    @$(PYTHON) manage.py test django_llm -v 2

test-fastapi: env-check
    @echo "$(BLUE)Running FastAPI tests...$(NC)"
    @$(PYTHON) manage.py test fastapi_app.tests -v 2

test-all: env-check
    @echo "$(BLUE)Running all tests...$(NC)"
    @$(PYTHON) manage.py test django_llm fastapi_app -v 2

pytest: env-check
    @echo "$(BLUE)Running pytest with coverage...$(NC)"
    @pytest --cov=django_llm --cov=fastapi_app --cov-report=term-missing

test-ollama: env-check
    @echo "$(BLUE)Testing Ollama connection...$(NC)"
    @$(PYTHON) test_ollama.py

test-api:
    @echo "$(BLUE)Testing API endpoints...$(NC)"
    @curl -s https://localhost:8443/api/health | $(PYTHON) -m json.tool

# -------------------------
# Database
# -------------------------

migrate: env-check
    @echo "$(BLUE)Running migrations...$(NC)"
    @$(PYTHON) manage.py makemigrations
    @$(PYTHON) manage.py migrate
    @echo "$(GREEN)✓ Migrations complete$(NC)"

migrate-check: env-check
    @echo "$(BLUE)Checking migration status...$(NC)"
    @$(PYTHON) manage.py makemigrations --check --dry-run

reset-db: env-check
    @echo "$(RED)⚠ Resetting database...$(NC)"
    @read -p "Are you sure? [y/N] " -n 1 -r; \
    echo; \
    if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
        find . -path "*/migrations/0*.py" -delete; \
        rm -f db.sqlite3; \
        $(PYTHON) manage.py makemigrations; \
        $(PYTHON) manage.py migrate; \
        echo "$(GREEN)✓ Database reset complete$(NC)"; \
    fi

# -------------------------
# Static files
# -------------------------

static: env-check
    @echo "$(BLUE)Collecting static files...$(NC)"
    @$(PYTHON) manage.py collectstatic --noinput
    @echo "$(GREEN)✓ Static files collected$(NC)"

# -------------------------
# Certificates
# -------------------------

certs:
    @echo "$(BLUE)Generating SSL certificates...$(NC)"
    @chmod +x generate_certs.sh && ./generate_certs.sh
    @echo "$(GREEN)✓ Certificates generated$(NC)"

check-certs:
    @echo "$(BLUE)Checking certificate validity...$(NC)"
    @$(PYTHON) manage.py check_certs

# -------------------------
# NGINX
# -------------------------

nginx:
    @echo "$(BLUE)Deploying NGINX configuration...$(NC)"
    @sudo cp nginx.conf /etc/nginx/sites-available/django_llm
    @sudo ln -sf /etc/nginx/sites-available/django_llm /etc/nginx/sites-enabled/
    @sudo rm -f /etc/nginx/sites-enabled/default
    @sudo nginx -t && sudo service nginx restart
    @echo "$(GREEN)✓ NGINX deployed$(NC)"

nginx-test:
    @echo "$(BLUE)Testing NGINX configuration...$(NC)"
    @sudo nginx -t

nginx-reload:
    @echo "$(BLUE)Reloading NGINX...$(NC)"
    @sudo service nginx reload
    @echo "$(GREEN)✓ NGINX reloaded$(NC)"

nginx-logs:
    @echo "$(BLUE)Tailing NGINX access logs...$(NC)"
    @sudo tail -f /var/log/nginx/django_llm_access.log

fastapi-logs:
    @echo "$(BLUE)Tailing FastAPI NGINX logs...$(NC)"
    @sudo tail -f /var/log/nginx/fastapi_access.log

# -------------------------
# Process management
# -------------------------

supervisor: env-check
    @echo "$(BLUE)Setting up supervisor...$(NC)"
    @sudo apt-get install -y supervisor
    @sudo cp django_llm_supervisor.conf /etc/supervisor/conf.d/django_llm.conf
    @sudo supervisorctl reread && sudo supervisorctl update
    @sudo supervisorctl start all
    @echo "$(GREEN)✓ Supervisor configured$(NC)"

supervisor-status:
    @echo "$(BLUE)Supervisor status:$(NC)"
    @sudo supervisorctl status

supervisor-restart:
    @echo "$(BLUE)Restarting supervisor services...$(NC)"
    @sudo supervisorctl restart all
    @echo "$(GREEN)✓ Services restarted$(NC)"

ps-check:
    @echo "$(BLUE)Checking running processes...$(NC)"
    @ps aux | grep -E "gunicorn|uvicorn|nginx" | grep -v grep

# -------------------------
# Django utilities
# -------------------------

superuser: env-check
    @echo "$(BLUE)Creating superuser...$(NC)"
    @$(PYTHON) manage.py createsuperuser

shell: env-check
    @echo "$(BLUE)Starting Django shell...$(NC)"
    @$(PYTHON) manage.py shell

check: env-check
    @echo "$(BLUE)Running Django checks...$(NC)"
    @$(PYTHON) manage.py check

check-deploy: env-check
    @echo "$(BLUE)Running deploy checks...$(NC)"
    @$(PYTHON) manage.py check --deploy

health:
    @echo "$(BLUE)System health check:$(NC)"
    @echo "  Django: $$(curl -s http://localhost:8000/health | $(PYTHON) -m json.tool 2>/dev/null | grep -q 'ok' && echo '$(GREEN)✓$(NC)' || echo '$(RED)✗$(NC)')"
    @echo "  FastAPI: $$(curl -s http://localhost:8001/api/health | $(PYTHON) -m json.tool 2>/dev/null | grep -q 'ok' && echo '$(GREEN)✓$(NC)' || echo '$(RED)✗$(NC)')"

# -------------------------
# API docs
# -------------------------

docs:
    @echo "$(GREEN)FastAPI documentation available at:$(NC)"
    @echo "  $(BLUE)Swagger: https://localhost:8443/api/docs$(NC)"
    @echo "  $(BLUE)ReDoc: https://localhost:8443/api/redoc$(NC)"
    @echo "  $(BLUE)OpenAPI JSON: https://localhost:8443/api/openapi.json$(NC)"

# -------------------------
# Logging
# -------------------------

logs:
    @echo "$(BLUE)Tailing debug log...$(NC)"
    @tail -f debug.log

logs-gunicorn:
    @echo "$(BLUE)Tailing Gunicorn logs...$(NC)"
    @tail -f /var/log/gunicorn_access.log

logs-uvicorn:
    @echo "$(BLUE)Tailing Uvicorn logs...$(NC)"
    @tail -f /var/log/uvicorn.out.log

logs-nginx:
    @echo "$(BLUE)Tailing NGINX logs...$(NC)"
    @sudo tail -f /var/log/nginx/django_llm_access.log

logs-mtls:
    @echo "$(BLUE)Tailing mTLS logs...$(NC)"
    @sudo tail -f /var/log/nginx/django_llm_mtls_access.log

logs-all:
    @echo "$(BLUE)Tailing all logs...$(NC)"
    @tail -f debug.log /var/log/gunicorn_access.log /var/log/uvicorn.out.log 2>/dev/null || true

# -------------------------
# Backup & Restore
# -------------------------

backup:
    @echo "$(BLUE)Creating backup...$(NC)"
    @mkdir -p backups
    @TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
    tar -czf backups/backup_$$TIMESTAMP.tar.gz db.sqlite3 django_llm/migrations/ && \
    echo "$(GREEN)✓ Backup created: backups/backup_$$TIMESTAMP.tar.gz$(NC)"

restore:
    @echo "$(BLUE)Available backups:$(NC)"
    @ls -lh backups/
    @read -p "Enter backup filename to restore: " backup_file; \
    if [ -f "backups/$$backup_file" ]; then \
        tar -xzf backups/$$backup_file; \
        echo "$(GREEN)✓ Backup restored$(NC)"; \
    else \
        echo "$(RED)✗ Backup not found$(NC)"; \
    fi

# -------------------------
# Cleanup
# -------------------------

clean:
    @echo "$(BLUE)Cleaning up...$(NC)"
    @find . -name "*.pyc" -delete
    @find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    @find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true
    @rm -f debug.log
    @echo "$(GREEN)✓ Cleanup complete$(NC)"

clean-summaries:
    @echo "$(RED)⚠ Clearing LLM summaries...$(NC)"
    @$(PYTHON) manage.py shell -c "from django_llm.models import LLMSummary; c = LLMSummary.objects.count(); LLMSummary.objects.all().delete(); print(f'$(GREEN)✓ Deleted {c} summaries$(NC)')"

clean-cache:
    @echo "$(BLUE)Clearing cache...$(NC)"
    @$(PYTHON) manage.py shell -c "from django.core.cache import cache; cache.clear(); print('$(GREEN)✓ Cache cleared$(NC)')"

clean-all: clean clean-cache
    @echo "$(GREEN)✓ Full cleanup complete$(NC)"

# -------------------------
# Installation
# -------------------------

install: env-check
    @echo "$(BLUE)Installing dependencies...$(NC)"
    @$(PIP) install -r requirements.txt --break-system-packages
    @echo "$(GREEN)✓ Dependencies installed$(NC)"

install-dev: install
    @echo "$(BLUE)Installing dev dependencies...$(NC)"
    @$(PIP) install pytest pytest-cov black flake8 --break-system-packages
    @echo "$(GREEN)✓ Dev dependencies installed$(NC)"

# -------------------------
# Code quality
# -------------------------

lint:
    @echo "$(BLUE)Running flake8...$(NC)"
    @flake8 django_llm/ fastapi_app/ --max-line-length=100 --exclude=migrations

format:
    @echo "$(BLUE)Formatting code with black...$(NC)"
    @black django_llm/ fastapi_app/ --exclude=migrations
    @echo "$(GREEN)✓ Code formatted$(NC)"

audit:
    @echo "$(BLUE)Running security audit...$(NC)"
    @$(PYTHON) -m pip install safety 2>/dev/null || true
    @safety check || true
    @echo "$(BLUE)Running django security check...$(NC)"
    @$(PYTHON) manage.py check --deploy
    @echo "$(GREEN)✓ Audit complete$(NC)"

# -------------------------
# Database utilities
# -------------------------

dump:
    @echo "$(BLUE)Dumping database...$(NC)"
    @TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
    $(PYTHON) manage.py dumpdata > db_dump_$$TIMESTAMP.json && \
    echo "$(GREEN)✓ Database dumped to db_dump_$$TIMESTAMP.json$(NC)"

load:
    @echo "$(BLUE)Available database dumps:$(NC)"
    @ls -lh db_dump_*.json
    @read -p "Enter dump filename to load: " dump_file; \
    if [ -f "$$dump_file" ]; then \
        $(PYTHON) manage.py loaddata $$dump_file; \
        echo "$(GREEN)✓ Data loaded$(NC)"; \
    else \
        echo "$(RED)✗ Dump file not found$(NC)"; \
    fi

# -------------------------
# Help
# -------------------------

help:
    @echo ""
    @echo "$(BLUE)Django LLM - Available commands:$(NC)"
    @echo ""
    @echo "$(GREEN)Setup & Environment:$(NC)"
    @echo "  make env-check          - Verify environment setup"
    @echo "  make ports-check        - Check if required ports are available"
    @echo "  make install            - Install dependencies"
    @echo "  make install-dev        - Install dev dependencies"
    @echo ""
    @echo "$(GREEN)Running:$(NC)"
    @echo "  make run                - Start full stack"
    @echo "  make dev                - Django dev server only"
    @echo "  make fastapi            - FastAPI dev server only"
    @echo "  make dev-all            - Django + FastAPI dev servers"
    @echo "  make gunicorn           - Django with Gunicorn"
    @echo "  make fastapi-gunicorn   - FastAPI with Gunicorn"
    @echo "  make docker-fastapi     - FastAPI in Docker"
    @echo ""
    @echo "$(GREEN)Testing:$(NC)"
    @echo "  make test               - Run Django tests"
    @echo "  make test-fastapi       - Run FastAPI tests"
    @echo "  make test-all           - Run all tests"
    @echo "  make pytest             - Run pytest with coverage"
    @echo "  make test-ollama        - Test Ollama connection"
    @echo "  make test-api           - Test API health"
    @echo ""
    @echo "$(GREEN)Database:$(NC)"
    @echo "  make migrate            - Run migrations"
    @echo "  make migrate-check      - Check migration status"
    @echo "  make reset-db           - Reset database (with confirmation)"
    @echo "  make dump               - Dump database to JSON"
    @echo "  make load               - Load database from JSON"
    @echo ""
    @echo "$(GREEN)Deployment:$(NC)"
    @echo "  make nginx              - Deploy NGINX config"
    @echo "  make nginx-reload       - Reload NGINX"
    @echo "  make certs              - Generate SSL certificates"
    @echo "  make supervisor         - Setup supervisor"
    @echo "  make supervisor-status  - Check supervisor status"
    @echo "  make supervisor-restart - Restart services"
    @echo ""
    @echo "$(GREEN)Monitoring:$(NC)"
    @echo "  make health             - System health check"
    @echo "  make ps-check           - Check running processes"
    @echo "  make logs               - Tail debug log"
    @echo "  make logs-all           - Tail all logs"
    @echo "  make docs               - Show API documentation URLs"
    @echo ""
    @echo "$(GREEN)Maintenance:$(NC)"
    @echo "  make backup             - Create database backup"
    @echo "  make restore            - Restore from backup"
    @echo "  make clean              - Remove .pyc files and cache"
    @echo "  make clean-cache        - Clear Django cache"
    @echo "  make clean-summaries    - Clear LLM summaries"
    @echo "  make clean-all          - Full cleanup"
    @echo "  make audit              - Security audit"
    @echo "  make lint               - Run flake8 linter"
    @echo "  make format             - Format code with black"
    @echo ""
    @echo "$(GREEN)Other:$(NC)"
    @echo "  make superuser          - Create admin user"
    @echo "  make shell              - Django shell"
    @echo "  make check              - Run Django checks"
    @echo "  make check-deploy       - Deployment checks"
    @echo "  make help               - Show this help"
    @echo ""
