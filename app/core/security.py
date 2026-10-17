import os
import re
import uuid
import hashlib
import tempfile
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Tuple
from fastapi import HTTPException, status
from PIL import Image
from app.config import (
    MAX_CONTENT_LENGTH,
    MAX_IMAGE_PIXELS,
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    MAGIC_BYTES,
)

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

SAFE_FILENAME_REGEX = re.compile(r"^[\w\-. ]+$")

def sanitize_filename(filename: str) -> str:
    if not filename:
        return f"evidence_{uuid.uuid4().hex[:8]}.bin"
    
    cleaned = os.path.basename(filename.strip().replace("\\", "/"))
    cleaned = cleaned.replace("\x00", "")
    
    parts = cleaned.rsplit(".", 1)
    stem = parts[0]
    ext = f".{parts[1].lower()}" if len(parts) > 1 else ""
    
    sanitized_stem = re.sub(r"[^\w\-.]", "_", stem)
    sanitized_stem = re.sub(r"_+", "_", sanitized_stem).strip("_.")
    
    if not sanitized_stem:
        sanitized_stem = f"sample_{uuid.uuid4().hex[:8]}"
        
    sanitized_name = f"{sanitized_stem[:64]}{ext}"
    return sanitized_name

def validate_upload(filename: str, content: bytes, content_type: str) -> Tuple[str, str]:
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
        
    if len(content) > MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size limit of {MAX_CONTENT_LENGTH // (1024 * 1024)}MB.",
        )

    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()
    
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File extension '{ext}' is not permitted.",
        )

    matched_format = detect_magic_format(content)
    if not matched_format:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not match any valid image magic signature.",
        )

    if ext in (".jpg", ".jpeg") and matched_format != "jpeg":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match JPEG binary signature.",
        )
    elif ext == ".png" and matched_format != "png":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match PNG binary signature.",
        )
    elif ext == ".webp" and matched_format != "webp":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match WebP binary signature.",
        )

    return safe_name, matched_format

def detect_magic_format(content: bytes) -> str | None:
    for fmt, sigs in MAGIC_BYTES.items():
        for sig in sigs:
            if fmt == "webp":
                if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                    return "webp"
            elif content.startswith(sig):
                return fmt
    return None

def compute_hashes(content: bytes) -> dict:
    return {
        "md5": hashlib.md5(content).hexdigest(),
        "sha1": hashlib.sha1(content).hexdigest(),
        "sha256": hashlib.sha256(content).hexdigest(),
    }

@contextmanager
def safe_temp_file(content: bytes, suffix: str = ".tmp") -> Generator[str, None, None]:
    temp_dir = tempfile.gettempdir()
    secure_prefix = f"metatracer_{uuid.uuid4().hex}_"
    temp_file = tempfile.NamedTemporaryFile(
        delete=False,
        dir=temp_dir,
        prefix=secure_prefix,
        suffix=suffix,
    )
    temp_path = temp_file.name
    try:
        temp_file.write(content)
        temp_file.flush()
        temp_file.close()
        yield temp_path
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
