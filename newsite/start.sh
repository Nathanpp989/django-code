#!/bin/bash
# =============================================================================
# Start script for Django LLM
# Starts Ollama, NGINX, Django/Gunicorn and FastAPI/Uvicorn
# =============================================================================

set -e

PROJECT_DIR="/workspaces/Django_code/newDjango"

echo "=============================="
echo "Starting Django LLM stack..."
echo "=============================="

# Start Ollama
echo "Starting Ollama..."
ollama serve &
sleep 2
echo "Ollama started"

# Start NGINX
echo "Starting NGINX..."
sudo service nginx start
echo "NGINX started"

cd $PROJECT_DIR

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Uvicorn (FastAPI) in background
echo "Starting FastAPI/Uvicorn on port 8001..."
uvicorn fastapi_app.main:app \
    --host 127.0.0.1 \
    --port 8001 \
    --workers 2 \
    --log-level info &
echo "FastAPI started"

# Start Gunicorn (Django) in foreground
echo "Starting Django/Gunicorn on port 8000..."
python -m gunicorn \
    --workers 3 \
    --timeout 120 \
    --log-level info \
    --access-logfile /var/log/gunicorn_access.log \
    --error-logfile /var/log/gunicorn_error.log \
    --bind 127.0.0.1:8000 \
    newsite.wsgi:application

echo "=============================="
echo "Stack is running"
echo "  Django UI:   https://localhost:8443"
echo "  FastAPI:     https://localhost:8443/api"
echo "  API Docs:    https://localhost:8443/api/docs"
echo "  Admin:       https://localhost:8443/admin"
echo "  Chat:        https://localhost:8443/chat"
echo "=============================="
