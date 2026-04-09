import os

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8001")
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

certfile = os.environ.get("GUNICORN_CERTFILE")
keyfile = os.environ.get("GUNICORN_KEYFILE")
ca_certs = os.environ.get("GUNICORN_CA_CERTS")