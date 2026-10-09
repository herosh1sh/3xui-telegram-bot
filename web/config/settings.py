from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT = BASE_DIR.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "heroshish-dev-key")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["*"]
INSTALLED_APPS = ["django.contrib.staticfiles", "cabinet"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "django.sqlite3"}}
STATIC_URL = "/assets/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
FRONTEND_DIST = ROOT / "frontend" / "dist"
