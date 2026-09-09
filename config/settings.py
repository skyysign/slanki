import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SLIDES_DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_ROOT = DATA_DIR / "media"
MEDIA_ROOT.mkdir(exist_ok=True)
WORK_DIR = DATA_DIR / "work"
WORK_DIR.mkdir(exist_ok=True)
secret_file = DATA_DIR / ".secret-key"
if not secret_file.exists():
    try:
        with secret_file.open("x", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
SECRET_KEY = secret_file.read_text(encoding="utf-8")
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.staticfiles", "converter"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "converter.middleware.LocalOnlyMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = DATA_DIR / "static"
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_TEMP_DIR = WORK_DIR
DATA_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 100
PDF_TIMEOUT = 120
GENERATION_TIMEOUT = 300
CODEX_BINARY = os.environ.get("SLIDES_CODEX_BINARY", "codex")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
