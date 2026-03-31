# =============================================================================
# Makefile for Django LLM
# Usage: make <command>
# =============================================================================

.PHONY: run dev test pytest migrate static certs nginx superuser shell clean logs help

# -------------------------
# Running
# -------------------------

run:
	@echo "Starting full stack..."
	@chmod +x start.sh && ./start.sh

dev:
	@echo "Starting development server..."
	@ollama serve & python manage.py runserver

gunicorn:
	@echo "Starting Gunicorn..."
	@python -m gunicorn --workers 3 --timeout 120 --bind 127.0.0.1:8000 --reload newsite.wsgi:application

# -------------------------
# Testing
# -------------------------

test:
	@echo "Running Django tests..."
	@python manage.py test django_llm -v 2

pytest:
	@echo "Running pytest with coverage..."
	@pytest --cov=django_llm --cov-report=term-missing

test-ollama:
	@echo "Testing Ollama integration..."
	@python test_ollama.py

# -------------------------
# Database
# -------------------------

migrate:
	@echo "Running migrations..."
	@python manage.py makemigrations && python manage.py migrate

migrate-check:
	@echo "Checking for missing migrations..."
	@python manage.py makemigrations --check --dry-run

reset-db:
	@echo "Resetting database..."
	@find . -path "*/migrations/0*.py" -delete
	@rm -f db.sqlite3
	@python manage.py makemigrations
	@python manage.py migrate
	@echo "Database reset complete"

# -------------------------
# Static files
# -------------------------

static:
	@echo "Collecting static files..."
	@python manage.py collectstatic --noinput

# -------------------------
# Certificates
# -------------------------

certs:
	@echo "Generating SSL certificates..."
	@chmod +x generate_certs.sh && ./generate_certs.sh

check-certs:
	@echo "Checking certificate expiry..."
	@python manage.py check_certs

# -------------------------
# NGINX
# -------------------------

nginx:
	@echo "Deploying NGINX config..."
	@sudo cp nginx.conf /etc/nginx/sites-available/django_llm
	@sudo ln -sf /etc/nginx/sites-available/django_llm /etc/nginx/sites-enabled/
	@sudo rm -f /etc/nginx/sites-enabled/default
	@sudo nginx -t && sudo service nginx restart
	@echo "NGINX deployed and restarted"

nginx-test:
	@sudo nginx -t

nginx-reload:
	@sudo service nginx reload

nginx-restart:
	@sudo service nginx restart

nginx-logs:
	@sudo tail -f /var/log/nginx/django_llm_access.log

# -------------------------
# Process management
# -------------------------

supervisor:
	@echo "Setting up supervisor..."
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
# Logs
# -------------------------

logs:
	@tail -f debug.log

logs-gunicorn:
	@tail -f /var/log/gunicorn_access.log

logs-nginx:
	@sudo tail -f /var/log/nginx/django_llm_access.log

logs-mtls:
	@sudo tail -f /var/log/nginx/django_llm_mtls_access.log

# -------------------------
# Cleanup
# -------------------------

clean:
	@echo "Cleaning up..."
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@rm -f debug.log
	@echo "Cleanup complete"

clean-summaries:
	@echo "Clearing LLM summaries from database..."
	@python manage.py shell -c "from django_llm.models import LLMSummary; count = LLMSummary.objects.count(); LLMSummary.objects.all().delete(); print(f'Deleted {count} summaries')"

# -------------------------
# Installation
# -------------------------

install:
	@echo "Installing dependencies..."
	@pip install -r requirements.txt --break-system-packages

install-dev:
	@echo "Installing dev dependencies..."
	@pip install -r requirements.txt pytest pytest-django coverage black flake8 --break-system-packages

# -------------------------
# Code quality
# -------------------------

lint:
	@echo "Running flake8..."
	@flake8 django_llm/ --max-line-length=100 --exclude=migrations

format:
	@echo "Running black..."
	@black django_llm/ --exclude=migrations

# -------------------------
# Help
# -------------------------

help:
	@echo ""
	@echo "Django LLM - Available commands:"
	@echo ""
	@echo "  Running:"
	@echo "    make run           - Start full stack (Ollama + NGINX + Gunicorn)"
	@echo "    make dev           - Start development server"
	@echo "    make gunicorn      - Start Gunicorn only"
	@echo ""
	@echo "  Testing:"
	@echo "    make test          - Run Django tests"
	@echo "    make pytest        - Run pytest with coverage"
	@echo "    make test-ollama   - Test Ollama integration"
	@echo ""
	@echo "  Database:"
	@echo "    make migrate       - Run migrations"
	@echo "    make reset-db      - Reset database completely"
	@echo ""
	@echo "  NGINX:"
	@echo "    make nginx         - Deploy NGINX config"
	@echo "    make nginx-logs    - Tail NGINX access logs"
	@echo ""
	@echo "  Utilities:"
	@echo "    make superuser     - Create Django superuser"
	@echo "    make shell         - Open Django shell"
	@echo "    make check-deploy  - Run Django deployment check"
	@echo "    make clean         - Remove .pyc files and logs"
	@echo "    make logs          - Tail debug.log"
	@echo ""
