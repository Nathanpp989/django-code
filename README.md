# Project run instructions

## Development (no systemd)

1. From the repository root, change into the Django project directory:

   cd newDjango

2. Copy the example env and set your secret:

   cp .env.example .env
   Edit `.env` and set `DJANGO_SECRET_KEY`, `DEBUG`, `DJANGO_ALLOWED_HOSTS`, and any database settings as needed.
   If using Redis caching, also set `REDIS_URL` or the cache backend values required by your settings.

   FastAPI validation and authentication:
   - The FastAPI API uses Pydantic schemas for input validation and Django session cookies for authentication.
   - Requests to `/api/*` must supply valid JSON payloads for field values such as `llm_text` and `choice_text`.
   - Validation rules include:
     - `llm_text` and `choice_text` are required strings
     - values cannot be empty and are limited to 200 characters
     - choice arrays must contain only non-empty strings

   FastAPI-related environment variables (defaults are usually safe for local development):
   - FASTAPI_ENABLED=True
   - FASTAPI_URL=http://127.0.0.1:8001
   - FASTAPI_DOCS_URL=/api/docs
   - FASTAPI_OPENAPI_URL=/api/openapi.json
   - FASTAPI_CORS_ALLOW_ORIGINS=https://localhost,https://127.0.0.1
   - FASTAPI_CORS_ALLOW_CREDENTIALS=True
   - FASTAPI_CACHE_TTL=30
   - FASTAPI_ROOT_TTL=60
   - FASTAPI_OLLAMA_CACHE_TTL=60
   - FASTAPI_DOCKER_HOST=unix:///var/run/docker.sock
   - FASTAPI_DOCKER_TIMEOUT=10

   Authentication notes:
   - Log in through Django at `/accounts/login/` to create a valid session.
   - FastAPI endpoints accept the Django `sessionid` cookie on `/api/*` requests.
   - If using a browser client across origins, enable credentials and forward the session cookie.

3. Create and activate a virtual environment, then install dependencies:

   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt

4. Run migrations:

   python manage.py makemigrations
   python manage.py migrate

5. Start the Django development server:

   python manage.py runserver 0.0.0.0:8000

6. Start the FastAPI process for API traffic:

   gunicorn -c newsite/gunicorn_conf.py fastapi_app.main:app

   # Or for local development:
   uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8001 --reload

7. If you need the ASGI/FastAPI stack via Django ASGI directly, use:

   uvicorn newsite.asgi:application --host 0.0.0.0 --port 8000 --reload

8. To start Gunicorn in the foreground:

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
- NGINX should proxy `/api` and `/api/*` to the FastAPI server on port `8001`, while routing HTML and Django pages to the Django Gunicorn backend on port `8000`.
- `ollama` and `mcp` are included for LLM / MCP integrations; check your app configuration for usage details.
- Always run migrations after model changes:

   python manage.py makemigrations
   python manage.py migrate
