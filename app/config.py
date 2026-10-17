import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "MetaTracer"
APP_SUBTITLE = "ExifDeepForensics"
APP_VERSION = "1.0.0"
AUTHOR = "AHMAD"
GITHUB_USER = "cys-dexter"
GITHUB_URL = "https://github.com/cys-dexter/MetaTracer"

MAX_CONTENT_LENGTH = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000

ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".tiff",
    ".tif",
    ".bmp",
}

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/tiff",
    "image/bmp",
}

MAGIC_BYTES = {
    "jpeg": [b"\xFF\xD8\xFF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "webp": [b"RIFF"],
    "gif": [b"GIF87a", b"GIF89a"],
    "tiff": [b"II*\x00", b"MM\x00*"],
    "bmp": [b"BM"],
}

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
