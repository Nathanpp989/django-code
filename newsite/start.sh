#!/bin/bash
# =============================================================================
# Start script for Django LLM
# Starts Ollama, NGINX, runs migrations and launches Gunicorn
#
# Usage:
#   chmod +x start.sh
#   ./start.sh
# =============================================================================

set -e

PROJECT_DIR="/workspaces/Django_code/newDjango"
LOG_DIR="/var/log"

echo "=============================="
echo "Starting Django LLM stack..."
echo "=============================="

# Start Ollama
echo "Starting Ollama..."
ollama serve &
OLLAMA_PID=$!
echo "Ollama started (PID: $OLLAMA_PID)"
sleep 2

# Start NGINX
echo "Starting NGINX..."
sudo service nginx start
echo "NGINX started"

# Change to project directory
cd $PROJECT_DIR

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput
echo "Migrations complete"

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput
echo "Static files collected"

# Run deployment check
echo "Running deployment check..."
python manage.py check --deploy 2>/dev/null || echo "Note: deployment warnings present (expected in dev)"

# Start Gunicorn
echo "Starting Gunicorn..."
python -m gunicorn \
    --workers 3 \
    --timeout 120 \
    --log-level info \
    --access-logfile $LOG_DIR/gunicorn_access.log \
    --error-logfile $LOG_DIR/gunicorn_error.log \
    --bind 127.0.0.1:8000 \
    newsite.wsgi:application

echo "=============================="
echo "Stack is running"
echo "  HTTP:  http://localhost"
echo "  HTTPS: https://localhost"
echo "  mTLS:  https://localhost:8443"
echo "  Admin: https://localhost:8443/admin"
echo "  Chat:  https://localhost:8443/chat"
echo "=============================="
