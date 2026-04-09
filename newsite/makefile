# =============================================================================
# Makefile for Django LLM
# Usage: make <command>
# =============================================================================

.PHONY: run dev test pytest fastapi migrate static certs nginx superuser shell clean logs help

# -------------------------
# Running
# -------------------------

run:
	@echo "Starting full stack..."
	@chmod +x start.sh && ./start.sh

dev:
	@echo "Starting Django development server..."
	@ollama serve & python manage.py runserver

fastapi:
	@echo "Starting FastAPI development server..."
	@uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8001 --reload

fastapi-gunicorn:
    @echo "Starting FastAPI with Gunicorn + Uvicorn workers..."
    @python -m gunicorn -c gunicorn_conf.py fastapi_app.main:app

dev-all:
	@echo "Starting Django + FastAPI in development mode..."
	@ollama serve &
	@uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8001 --reload &
	@python manage.py runserver

gunicorn:
	@python -m gunicorn --workers 3 --timeout 120 --bind 127.0.0.1:8000 --reload newsite.wsgi:application

uvicorn:
	@uvicorn fastapi_app.main:app --host 127.0.0.1 --port 8001 --workers 2

docker-fastapi:
    @echo "Starting FastAPI container with Docker socket access..."
    @cd .. && docker-compose up --build fastapi

# -------------------------
# Testing
# -------------------------

test:
	@echo "Running Django tests..."
	@python manage.py test django_llm -v 2

test-fastapi:
	@echo "Running FastAPI tests..."
	@python manage.py test fastapi_app.tests -v 2

test-all:
	@echo "Running all tests..."
	@python manage.py test django_llm fastapi_app -v 2

pytest:
	@pytest --cov=django_llm --cov=fastapi_app --cov-report=term-missing

test-ollama:
	@python test_ollama.py

# -------------------------
# Database
# -------------------------

migrate:
	@python manage.py makemigrations && python manage.py migrate

migrate-check:
	@python manage.py makemigrations --check --dry-run

reset-db:
	@find . -path "*/migrations/0*.py" -delete
	@rm -f db.sqlite3
	@python manage.py makemigrations && python manage.py migrate

# -------------------------
# Static files
# -------------------------

static:
	@python manage.py collectstatic --noinput

# -------------------------
# Certificates
# -------------------------

certs:
	@chmod +x generate_certs.sh && ./generate_certs.sh

check-certs:
	@python manage.py check_certs

# -------------------------
# NGINX
# -------------------------

nginx:
	@sudo cp nginx.conf /etc/nginx/sites-available/django_llm
	@sudo ln -sf /etc/nginx/sites-available/django_llm /etc/nginx/sites-enabled/
	@sudo rm -f /etc/nginx/sites-enabled/default
	@sudo nginx -t && sudo service nginx restart

nginx-test:
	@sudo nginx -t

nginx-reload:
	@sudo service nginx reload

nginx-logs:
	@sudo tail -f /var/log/nginx/django_llm_access.log

fastapi-logs:
	@sudo tail -f /var/log/nginx/fastapi_access.log

# -------------------------
# Process management
# -------------------------

supervisor:
	@sudo apt-get install -y supervisor
	@sudo cp django_llm_supervisor.conf /etc/supervisor/conf.d/django_llm.conf
	@sudo supervisorctl reread && sudo supervisorctl update
	@sudo supervisorctl start all

supervisor-status:
	@sudo supervisorctl status

supervisor-restart:
	@sudo supervisorctl restart all

# -------------------------
# Django utilities
# -------------------------

superuser:
	@python manage.py createsuperuser

shell:
	@python manage.py shell

check:
	@python manage.py check

check-deploy:
	@python manage.py check --deploy

# -------------------------
# API docs
# -------------------------

docs:
	@echo "FastAPI docs available at:"
	@echo "  https://localhost:8443/api/docs"
	@echo "  https://localhost:8443/api/redoc"

# -------------------------
# Logs
# -------------------------

logs:
	@tail -f debug.log

logs-gunicorn:
	@tail -f /var/log/gunicorn_access.log

logs-uvicorn:
	@tail -f /var/log/uvicorn.out.log

logs-nginx:
	@sudo tail -f /var/log/nginx/django_llm_access.log

logs-mtls:
	@sudo tail -f /var/log/nginx/django_llm_mtls_access.log

# -------------------------
# Cleanup
# -------------------------

clean:
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@rm -f debug.log

clean-summaries:
	@python manage.py shell -c "from django_llm.models import LLMSummary; c = LLMSummary.objects.count(); LLMSummary.objects.all().delete(); print(f'Deleted {c} summaries')"

# -------------------------
# Installation
# -------------------------

install:
	@pip install -r requirements.txt --break-system-packages

# -------------------------
# Code quality
# -------------------------

lint:
	@flake8 django_llm/ fastapi_app/ --max-line-length=100 --exclude=migrations

format:
	@black django_llm/ fastapi_app/ --exclude=migrations

# -------------------------
# Help
# -------------------------

help:
	@echo ""
	@echo "Django LLM - Available commands:"
	@echo ""
	@echo "  Running:"
	@echo "    make run           - Start full stack"
	@echo "    make dev           - Django dev server only"
	@echo "    make fastapi       - FastAPI dev server only"
	@echo "    make dev-all       - Django + FastAPI dev servers"
	@echo ""
	@echo "  Testing:"
	@echo "    make test          - Run Django tests"
	@echo "    make test-fastapi  - Run FastAPI tests"
	@echo "    make test-all      - Run all tests"
	@echo "    make pytest        - Run pytest with coverage"
	@echo ""
	@echo "  API:"
	@echo "    make docs          - Show API docs URLs"
	@echo "    make fastapi-logs  - Tail FastAPI NGINX logs"
	@echo ""
	@echo "  Database:"
	@echo "    make migrate       - Run migrations"
	@echo "    make reset-db      - Reset database"
	@echo ""
	@echo "  Other:"
	@echo "    make nginx         - Deploy NGINX config"
	@echo "    make certs         - Generate SSL certificates"
	@echo "    make supervisor    - Set up supervisor"
	@echo "    make help          - Show this help"
	@echo ""
