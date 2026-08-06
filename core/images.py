"""Photo processing for registration photos.

Phone originals are 4–6 MB; neither rendition below is anywhere near that.
Both are produced synchronously in the upload request — a Pillow resize of a
phone photo is sub-second, so this needs no queue (see storage_plan.md).
"""

from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_DIMENSION = 1600
THUMB_DIMENSION = 320
JPEG_QUALITY = 82
THUMB_QUALITY = 75


def _prepare(uploaded_file):
    """Open, apply EXIF rotation, and force a JPEG-safe mode.

    exif_transpose matters: phone photos are usually stored unrotated with an
    orientation tag, so skipping it shows site photos on their side.
    """
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return image


def _encode(image, quality):
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return ContentFile(buffer.getvalue())


def process_upload(uploaded_file):
    """Full-size rendition: downscaled, re-encoded, metadata stripped."""
    image = _prepare(uploaded_file)
    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    return _encode(image, JPEG_QUALITY)


def make_thumbnail(uploaded_file):
    """Small rendition for list and grid views."""
    image = _prepare(uploaded_file)
    image.thumbnail((THUMB_DIMENSION, THUMB_DIMENSION))
    return _encode(image, THUMB_QUALITY)


def process_photo(uploaded_file):
    """Both renditions from one upload, as (full, thumbnail).

    Read the file once and hand each pass its own buffer — Pillow leaves the
    original file object consumed, so a second _prepare on it would fail.
    """
    raw = uploaded_file.read()
    return process_upload(BytesIO(raw)), make_thumbnail(BytesIO(raw))
