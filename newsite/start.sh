#!/bin/bash
echo "Starting Django LLM stack..."

# Start Ollama
ollama serve &
echo "Ollama started"
sleep 2

# Start NGINX
sudo service nginx start
echo "NGINX started"

# Run migrations
python manage.py migrate
echo "Migrations complete"

# Collect static files
python manage.py collectstatic --noinput
echo "Static files collected"

# Start Gunicorn
echo "Starting Gunicorn..."
python -m gunicorn --workers 3 \
    --log-level info \
    --access-logfile /var/log/gunicorn_access.log \
    --error-logfile /var/log/gunicorn_error.log \
    newsite.wsgi:application
    