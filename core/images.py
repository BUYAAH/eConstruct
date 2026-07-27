"""Photo processing for note attachments."""

from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_DIMENSION = 1600
JPEG_QUALITY = 82


def process_upload(uploaded_file):
    """Downscale an uploaded photo and re-encode as JPEG.

    Applies the EXIF orientation (phone photos are often stored rotated),
    caps the longest side at MAX_DIMENSION, and strips metadata.
    """
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY)
    return ContentFile(buffer.getvalue())
