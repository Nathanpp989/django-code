from pathlib import Path
import os
import secrets
from dotenv import load_dotenv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(str(BASE_DIR / ".env"))

DEBUG = os.getenv("DEBUG", "True").lower() in ("1", "true", "yes")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = secrets.token_urlsafe(50)
    else:
        raise ValueError("DJANGO_SECRET_KEY must be set in production")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

# Validate required production environment variables
REQUIRED_ENV_VARS = (
    []
    if DEBUG
    else [
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DATABASE_URL",
    ]
)
missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing:
    raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

CSRF_TRUSTED_ORIGINS = []
if not DEBUG and ALLOWED_HOSTS:
    for host in ALLOWED_HOSTS:
        if not host or host in ("localhost", "127.0.0.1"):
            continue
        if host.startswith("http://") or host.startswith("https://"):
            CSRF_TRUSTED_ORIGINS.append(host)
        else:
            CSRF_TRUSTED_ORIGINS.append(f"https://{host}")

# -------------------------
# FastAPI Integration
# -------------------------
FASTAPI_ENABLED = os.getenv("FASTAPI_ENABLED", "True").lower() in ("1", "true", "yes")
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:8001")
FASTAPI_API_TIMEOUT = int(os.getenv("FASTAPI_API_TIMEOUT", "30"))

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# -------------------------
# Security
# -------------------------
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 0 if DEBUG else 63072000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SESSION_COOKIE_AGE = 1209600
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False

# Additional security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Content Security Policy (basic)
SECURE_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)

# -------------------------
# Client Certificate Settings
# -------------------------
CLIENT_CERT_EXEMPT_PATHS = [
    "/accounts/login/",
    "/accounts/logout/",
    "/static/",
    "/media/",
    "/favicon.ico",
    "/robots.txt",
    "/admin/login/",
    "/health/",
]

# -------------------------
# Applications
# -------------------------
INSTALLED_APPS = [
    "django_llm.apps.DjangoLlmConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "corsheaders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django_llm.middleware.ClientCertificateMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# -------------------------
# CORS Settings (for FastAPI integration)
# -------------------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "https://localhost:8443",
    "https://127.0.0.1:8443",
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

ROOT_URLCONF = "newsite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "newsite.wsgi.application"

# -------------------------
# Database
# -------------------------
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}

# -------------------------
# Password Validation
# -------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -------------------------
# Cache
# -------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# Fallback to database cache if Redis is not available
if not os.getenv("REDIS_URL"):
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "rate_limit_cache",
    }
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# -------------------------
# Static Files
# -------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

if not DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -------------------------
# Auth Redirects
# -------------------------
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
LOGIN_URL = "/accounts/login/"

# -------------------------
# Caching
# -------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "django-llm-cache",
        "OPTIONS": {
            "MAX_ENTRIES": 10000,
        },
    }
}

# -------------------------
# Session Configuration
# -------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_CACHE_ALIAS = "default"

# -------------------------
# Ollama Settings
# -------------------------
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "200"))
OLLAMA_CACHE_TIMEOUT = int(os.getenv("OLLAMA_CACHE_TIMEOUT", "300"))

# -------------------------
# Logging
# -------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "debug.log",
            "formatter": "verbose",
            "level": "DEBUG" if DEBUG else "INFO",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "fastapi": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "fastapi.log",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["file", "console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["file", "console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django_llm": {
            "handlers": ["file", "console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "fastapi": {
            "handlers": ["fastapi", "console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
