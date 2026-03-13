#!/bin/bash
echo "Starting Django LLM stack..."

# Start Ollama in background
echo "Starting Ollama..."
ollama serve &
OLLAMA_PID=$!
echo "Ollama started (PID: $OLLAMA_PID)"

# Wait for Ollama to be ready
sleep 2

# Start NGINX
echo "Starting NGINX..."
sudo service nginx start

# Run migrations
echo "Running migrations..."
python manage.py migrate

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Gunicorn
echo "Starting Gunicorn..."
python -m gunicorn --workers 3 \
    --log-level info \
    --access-logfile /var/log/gunicorn_access.log \
    --error-logfile /var/log/gunicorn_error.log \
    newsite.wsgi:application

echo "Stack is running at http://localhost"