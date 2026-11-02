import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
IS_TESTING = "test" in sys.argv


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


class ImproperlyConfiguredForProduction(Exception):
    """Raised at import time when a production deploy is missing a required secret."""


# DEBUG defaults to False. A production box that is missing its .env now serves
# safely instead of exposing tracebacks and settings; developers opt in locally.
DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or IS_TESTING:
        SECRET_KEY = "django-insecure-local-development-only-key"
    else:
        raise ImproperlyConfiguredForProduction(
            "SECRET_KEY is not set. Generate one with:\n"
            "  python -c \"from django.core.management.utils import get_random_secret_key;"
            " print(get_random_secret_key())\"\n"
            "then add it to .env before starting the server."
        )

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,testserver" if (DEBUG or IS_TESTING) else "",
)
if not DEBUG and not IS_TESTING and not ALLOWED_HOSTS:
    raise ImproperlyConfiguredForProduction(
        "ALLOWED_HOSTS must be set when DEBUG is off, e.g. "
        "ALLOWED_HOSTS=ithihasam.in,www.ithihasam.in"
    )


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_ckeditor_5",
    "corsheaders",
    "rest_framework",
    "finoraapp",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not DEBUG and not IS_TESTING:
    MIDDLEWARE.insert(2, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "finorabackend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "finorabackend.wsgi.application"


DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
database_config_kwargs = {
    "default": DATABASE_URL,
    "conn_max_age": int(os.getenv("DATABASE_CONN_MAX_AGE", "600")),
}
if not DATABASE_URL.startswith("sqlite"):
    database_config_kwargs["ssl_require"] = env_bool("DATABASE_SSL_REQUIRE", not DEBUG)

DATABASES = {
    "default": dj_database_url.config(**database_config_kwargs)
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True
# Used to build absolute URLs in sitemap.xml. Must be https in production or the
# sitemap advertises URLs that do not match the site's canonical tags.
SITE_URL = (os.getenv("SITE_URL", "http://localhost:8080" if DEBUG else "https://ithihasam.in")).rstrip("/")
if not DEBUG and not IS_TESTING and not SITE_URL.startswith("https://"):
    raise ImproperlyConfiguredForProduction(
        f"SITE_URL must use https in production (got {SITE_URL!r}). "
        "Canonical tags and sitemap entries have to agree on the protocol."
    )


STATIC_URL = os.getenv("STATIC_URL", "/static/")
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = os.getenv("MEDIA_URL", "/media/")
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # The manifest backend requires collectstatic to have run, which is not
        # the case under `manage.py test`. Any test rendering an admin template
        # would otherwise fail on a missing manifest entry rather than on
        # anything to do with the code under test.
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if IS_TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
WHITENOISE_MAX_AGE = int(os.getenv("WHITENOISE_MAX_AGE", "31536000"))


FRONTEND_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080" if DEBUG else "",
)
CORS_ALLOWED_ORIGINS = FRONTEND_ORIGINS
CORS_ALLOW_CREDENTIALS = env_bool("CORS_ALLOW_CREDENTIALS", False)
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", False)

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    ",".join(FRONTEND_ORIGINS),
)


REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        *(
            ["rest_framework.renderers.BrowsableAPIRenderer"]
            if DEBUG
            else []
        ),
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "contact_submissions": os.getenv("CONTACT_SUBMISSION_THROTTLE_RATE", "10/hour"),
        # Analytics is high-volume by nature: one browsing session sends several
        # batches. Generous, but still bounded against a flood.
        "analytics_ingest": os.getenv("ANALYTICS_THROTTLE_RATE", "240/hour"),
    },
}


EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "30"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@ithihasa.local")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
BOOKING_NOTIFICATION_EMAILS = env_list(
    "BOOKING_NOTIFICATION_EMAILS",
    EMAIL_HOST_USER if EMAIL_HOST_USER else "",
)


CKEDITOR_5_FILE_UPLOAD_PERMISSION = "staff"
CKEDITOR_5_FILE_STORAGE = "finoraapp.storages.CKEditor5Storage"
CKEDITOR_5_UPLOAD_FILE_TYPES = ["jpeg", "jpg", "png", "gif", "webp"]
CKEDITOR_5_CONFIGS = {
    "blog": {
        "toolbar": [
            "heading",
            "|",
            "bold",
            "italic",
            "underline",
            "strikethrough",
            "|",
            "numberedList",
            "bulletedList",
            "todoList",
            "blockQuote",
            "|",
            "alignment",
            "outdent",
            "indent",
            "|",
            "link",
            "insertImage",
            "insertTable",
            "horizontalLine",
            "specialCharacters",
            "|",
            "removeFormat",
            "sourceEditing",
            "undo",
            "redo",
        ],
        "heading": {
            "options": [
                {"model": "paragraph", "title": "Paragraph", "class": "ck-heading_paragraph"},
                {"model": "heading1", "view": "h1", "title": "Heading 1", "class": "ck-heading_heading1"},
                {"model": "heading2", "view": "h2", "title": "Heading 2", "class": "ck-heading_heading2"},
                {"model": "heading3", "view": "h3", "title": "Heading 3", "class": "ck-heading_heading3"},
            ]
        },
        "image": {
            "toolbar": [
                "imageTextAlternative",
                "toggleImageCaption",
                "imageStyle:inline",
                "imageStyle:alignLeft",
                "imageStyle:alignCenter",
                "imageStyle:alignRight",
                "linkImage",
            ],
        },
        "table": {
            "contentToolbar": [
                "tableColumn",
                "tableRow",
                "mergeTableCells",
                "tableProperties",
                "tableCellProperties",
            ]
        },
        "simpleUpload": {
            "maxFileSize": 2 * 1024 * 1024,
        },
        "link": {
            "addTargetToExternalLinks": True,
            "defaultProtocol": "https://",
        },
    }
}


APPEND_SLASH = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", not DEBUG and not IS_TESTING)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG and not IS_TESTING)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG and not IS_TESTING)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG and not IS_TESTING)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000" if not DEBUG and not IS_TESTING else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG and not IS_TESTING)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", not DEBUG and not IS_TESTING)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.getenv("SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "Lax")
X_FRAME_OPTIONS = "DENY"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
        },
        "finoraapp": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

# Optional local GeoIP City database (DB-IP City Lite or MaxMind GeoLite2).
# When unset, analytics records no location rather than sending visitor IPs
# to a third-party lookup service.
#   pip install geoip2  &&  download the .mmdb  &&  set GEOIP_CITY_DB
GEOIP_CITY_DB = os.getenv("GEOIP_CITY_DB", "")

# Analytics rows hold IP addresses, which are personal data under the DPDP Act.
# They are purged after this many days; keeping them indefinitely is not allowed.
ANALYTICS_RETENTION_DAYS = int(os.getenv("ANALYTICS_RETENTION_DAYS", "90"))
