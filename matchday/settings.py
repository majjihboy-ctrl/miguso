import os
from pathlib import Path
from decouple import config

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-me")
DEBUG = config("DEBUG", default=False, cast=bool)

if not DEBUG and SECRET_KEY == "django-insecure-change-me":
    raise ImproperlyConfigured(
        "SECRET_KEY is still set to the insecure default while DEBUG=False. "
        "Set a real SECRET_KEY environment variable before deploying."
    )

# Vercel sets VERCEL=1 in the function's environment automatically. Used
# below to skip filesystem operations that aren't safe in that environment
# (only /tmp is writable there, and it doesn't persist between invocations).
IS_VERCEL = config("VERCEL", default=False, cast=bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="127.0.0.1,localhost",
    cast=lambda v: [s.strip() for s in v.split(",")],
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    "import_export",
    "django_ratelimit",
    "predictions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "matchday.urls"

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

WSGI_APPLICATION = "matchday.wsgi.application"
ASGI_APPLICATION = "matchday.asgi.application"

# Database
import dj_database_url
DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "predictions" / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_REDIRECT_URL = "home"
LOGIN_URL = "login"

# Security
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default=",".join(f"https://{h}" for h in ALLOWED_HOSTS if h not in ("127.0.0.1", "localhost")),
    cast=lambda v: [s.strip() for s in v.split(",") if s.strip()],
)
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# Sessions
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 1209600

# Redis cache. Points at localhost by default for local dev; in production
# (Vercel or anywhere else) set REDIS_URL to a real managed Redis instance
# (e.g. Upstash via the Vercel Marketplace) — there is no local Redis
# process available inside a Vercel serverless function.
REDIS_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/1")
_connection_pool_kwargs = {
    "protocol": 2,  # This forces Redis to skip the HELLO command
}
if REDIS_URL.startswith("rediss://"):
    # Most managed providers (Upstash included) terminate TLS with a cert
    # that Python's default verification is picky about from inside
    # serverless runtimes. Relaxing verification here is the commonly
    # recommended workaround for django-redis + rediss://.
    # NOTE: previously this key was re-declared via a `**{...}` unpack
    # inside the same dict literal, which (since it's the same key,
    # "CONNECTION_POOL_KWARGS") silently overwrote the dict above instead
    # of merging into it — protocol=2 was being lost on every rediss://
    # connection. Building the dict in two steps and updating it instead
    # keeps both settings.
    _connection_pool_kwargs["ssl_cert_reqs"] = None

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": _connection_pool_kwargs,
        }
    }
}

# Stripe
STRIPE_PUBLISHABLE_KEY = config("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY = config("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = config("STRIPE_WEBHOOK_SECRET", default="")

# Logging
# File logging is only safe on a filesystem that's actually writable and
# persistent. Vercel functions only expose a writable /tmp that doesn't
# survive between invocations, so on Vercel we log to stdout only (visible
# in the Vercel dashboard's function logs) and skip the file handler
# entirely rather than crashing on LOGS_DIR.mkdir().
LOG_HANDLERS = {
    "console": {
        "level": "DEBUG" if DEBUG else "INFO",
        "class": "logging.StreamHandler",
        "formatter": "verbose",
    },
}

if not IS_VERCEL:
    LOGS_DIR = BASE_DIR / "logs"
    LOGS_DIR.mkdir(exist_ok=True)
    LOG_HANDLERS["file"] = {
        "level": "ERROR",
        "class": "logging.FileHandler",
        "filename": LOGS_DIR / "django.log",
        "formatter": "verbose",
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} [{levelname}] {name}: {message}",
            "style": "{",
        },
    },
    "handlers": LOG_HANDLERS,
    "loggers": {
        "django": {
            "handlers": list(LOG_HANDLERS.keys()),
            "level": "ERROR",
            "propagate": True,
        },
        # Catches logger.exception()/logger.warning() calls added in
        # views.py (e.g. Stripe webhook errors, unknown-customer warnings)
        # that previously had nowhere to go.
        "predictions": {
            "handlers": list(LOG_HANDLERS.keys()),
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Optional: for real-time error visibility in production, wire up Sentry
# (or similar) here, e.g.:
#
#   import sentry_sdk
#   from sentry_sdk.integrations.django import DjangoIntegration
#   SENTRY_DSN = config("SENTRY_DSN", default="")
#   if SENTRY_DSN:
#       sentry_sdk.init(dsn=SENTRY_DSN, integrations=[DjangoIntegration()], traces_sample_rate=0.1)