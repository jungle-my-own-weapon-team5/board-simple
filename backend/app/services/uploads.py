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
