"""Safe image upload handling.

Images are decoded with Pillow (content sniffing, not trusting the filename or
Content-Type), size/pixel limited, auto-rotated, stripped of metadata and
re-encoded under a random server-generated name.
"""
import os
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SIDE = 1600


class ImageError(Exception):
    pass


def save_image(file_storage, upload_dir: str, max_bytes: int, max_pixels: int) -> str:
    name = (file_storage.filename or "").lower()
    if os.path.splitext(name)[1] not in ALLOWED_EXT:
        raise ImageError("Only JPG, PNG or WEBP images are allowed.")
    data = file_storage.stream.read(max_bytes + 1)
    if not data:
        raise ImageError("An uploaded image was empty.")
    if len(data) > max_bytes:
        raise ImageError(f"Each image must be smaller than {max_bytes // (1024 * 1024)} MB.")
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        probe = Image.open(BytesIO(data))
        if probe.format not in FORMATS:
            raise ImageError("Only JPG, PNG or WEBP images are allowed.")
        probe.verify()
        img = Image.open(BytesIO(data))
        if img.width * img.height > max_pixels:
            raise ImageError("Image dimensions are too large.")
        fmt = img.format
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        if fmt == "JPEG" and img.mode != "RGB":
            img = img.convert("RGB")
        elif fmt != "JPEG" and img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode else "RGB")
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ImageError("One of the files is not a valid image.")

    filename = f"{uuid.uuid4().hex}.{FORMATS[fmt]}"
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    try:
        img.save(os.path.join(upload_dir, filename), format=fmt)   # re-encode: drops metadata
    except OSError:
        raise ImageError("Could not process one of the images.")
    return filename


def remove_files(upload_dir: str, filenames) -> None:
    for fn in filenames:
        # filenames come from our own DB, but never allow path traversal anyway
        if fn and os.path.basename(fn) == fn:
            try:
                os.remove(os.path.join(upload_dir, fn))
            except OSError:
                pass
