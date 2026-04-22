# Project run instructions

## Development (no systemd)

1. From the repository root, change into the Django project directory:

   cd newDjango

2. Copy the example env and set your secret:

   cp .env.example .env
   # Edit .env and set DJANGO_SECRET_KEY, DEBUG, ALLOWED_HOSTS, and any DB settings as needed
   # If using Redis caching, also set REDIS_URL or the cache backend values required by your settings

3. Create and activate a virtual environment, then install dependencies:

   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt

4. Run migrations:

   python manage.py makemigrations
   python manage.py migrate

5. Start the Django development server:

   python manage.py runserver 0.0.0.0:8000

6. If you need the ASGI/FastAPI stack, start uvicorn:

   uvicorn newsite.asgi:application --host 0.0.0.0 --port 8000 --reload

7. To start Gunicorn in the foreground:

   gunicorn --chdir /workspaces/Django_code/newDjango --workers 3 --bind unix:/workspaces/Django_code/newDjango/gunicorn.sock newsite.wsgi:application

8. To run in the background (as `codespace` user):

   sudo -u codespace /home/codespace/.python/current/bin/gunicorn \
     --chdir /workspaces/Django_code/newDjango \
     --workers 3 \
     --bind unix:/workspaces/Django_code/newDjango/gunicorn.sock \
     newsite.wsgi:application --daemon

## Systemd (production host with systemd)

1. Copy unit files to systemd and enable:

   sudo cp newDjango/gunicorn.socket /etc/systemd/system/
   sudo cp newDjango/gunicorn.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now gunicorn.socket
   sudo systemctl restart --now gunicorn.service
   sudo systemctl status --no-pager gunicorn.socket gunicorn.service

2. Logs:

   sudo journalctl -u gunicorn.service -f

## Notes

- Ensure the `User` in `gunicorn.service` matches the account that owns the project files and the `SocketUser` in `gunicorn.socket`.
- If the socket is project-local, ensure the configured user can create the socket path.
- `python-dotenv` loads environment variables from `.env`; keep secrets out of source control.
- `django-redis` / `redis` support is included, so install/start a local Redis instance if you use caching.
- FastAPI / uvicorn are included for ASGI endpoints and async HTTP handling.
- `ollama` and `mcp` are included for LLM / MCP integrations; check your app configuration for usage details.
- Always run migrations after model changes:

   python manage.py makemigrations
   python manage.py migrate
