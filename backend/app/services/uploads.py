import base64
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings

ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def save_upload(file: UploadFile | None, user_id: int, kind: str) -> str | None:
    if file is None:
        return None
    suffix = ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if suffix is None:
        raise HTTPException(status_code=400, detail="Only jpeg, png, and webp images are supported")

    root = Path(get_settings().upload_dir)
    target_dir = root / "meals" / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{kind}-{uuid4().hex}{suffix}"
    path = target_dir / name
    with path.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            output.write(chunk)
    return "/" + str(path).replace("\\", "/")


def save_data_url(data_url: str | None, user_id: int, kind: str) -> str | None:
    if not data_url:
        return None
    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,(.+)", data_url, flags=re.DOTALL)
    if match is None:
        raise HTTPException(status_code=400, detail="Invalid food image data")
    content_type, encoded = match.groups()
    suffix = ALLOWED_IMAGE_TYPES.get(content_type)
    if suffix is None:
        raise HTTPException(status_code=400, detail="Only jpeg, png, and webp images are supported")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid food image data") from exc
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Food image is too large")

    root = Path(get_settings().upload_dir)
    target_dir = root / "meals" / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{kind}-{uuid4().hex}{suffix}"
    path.write_bytes(image_bytes)
    return "/" + str(path).replace("\\", "/")
