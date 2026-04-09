FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV FASTAPI_DOCKER_HOST=unix:///var/run/docker.sock
EXPOSE 8001

CMD ["gunicorn", "-c", "newsite/gunicorn_conf.py", "fastapi_app.main:app"]