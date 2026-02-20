Project run instructions

Development (no systemd):

1. Copy the example env and set your secret:

   cp .env.example .env
   # Edit .env and set DJANGO_SECRET_KEY, DEBUG as needed

2. Run migrations and start gunicorn (foreground):

   source <your-venv>/bin/activate
   python manage.py migrate
   gunicorn --chdir /workspaces/Django_code/newDjango --workers 3 --bind unix:/workspaces/Django_code/newDjango/gunicorn.sock newsite.wsgi:application

3. To run in background (as `codespace` user):

   sudo -u codespace /home/codespace/.python/current/bin/gunicorn \
     --chdir /workspaces/Django_code/newDjango \
     --workers 3 \
     --bind unix:/workspaces/Django_code/newDjango/gunicorn.sock \
     newsite.wsgi:application --daemon

Systemd (production host with systemd):

1. Copy unit files to systemd and enable:

   sudo cp newDjango/gunicorn.socket /etc/systemd/system/
   sudo cp newDjango/gunicorn.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now gunicorn.socket
   sudo systemctl restart --now gunicorn.service
   sudo systemctl status --no-pager gunicorn.socket gunicorn.service

2. Logs:

   sudo journalctl -u gunicorn.service -f

Notes:
- Ensure the `User` in `gunicorn.service` matches the account that owns the project files and the `SocketUser` in `gunicorn.socket`.
- If the socket is project-local, ensure the configured user can create the socket path.
- Always run migrations after model changes:

   python manage.py makemigrations
   python manage.py migrate
