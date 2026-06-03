import io
import uuid

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import PhotoStatus
from app.infrastructure.db.models import Photo
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.storage.r2 import StorageService

settings = get_settings()
redis_conn = Redis.from_url(settings.redis_url)
queue = Queue("default", connection=redis_conn)


def enqueue_image_processing(photo_id: str) -> None:
    queue.enqueue(process_image, photo_id, job_timeout=600)


def process_image(photo_id: str) -> None:
    db: Session = SessionLocal()
    try:
        photo = db.query(Photo).filter(Photo.id == uuid.UUID(photo_id)).first()
        if not photo:
            return

        storage = StorageService()
        try:
            raw = storage.download_object(photo.original_object_key)
            img = Image.open(io.BytesIO(raw))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            width, height = img.size

            thumb = img.copy()
            thumb.thumbnail((400, 400))
            thumb_buf = io.BytesIO()
            thumb.save(thumb_buf, format="WEBP", quality=80)
            thumb_key = f"events/{photo.event_id}/thumb/{photo.id}.webp"
            storage.upload_bytes(thumb_key, thumb_buf.getvalue(), "image/webp")

            compressed = img.copy()
            compressed.thumbnail((1800, 1800))
            comp_buf = io.BytesIO()
            compressed.save(comp_buf, format="WEBP", quality=82)
            comp_key = f"events/{photo.event_id}/compressed/{photo.id}.webp"
            storage.upload_bytes(comp_key, comp_buf.getvalue(), "image/webp")

            photo.thumbnail_object_key = thumb_key
            photo.compressed_object_key = comp_key
            photo.width = width
            photo.height = height
            photo.status = PhotoStatus.PENDING
            photo.upload_error = None
        except Exception as exc:
            photo.status = PhotoStatus.FAILED
            photo.upload_error = str(exc)
        db.commit()
    finally:
        db.close()
