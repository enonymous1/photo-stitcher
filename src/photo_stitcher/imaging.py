"""Full-resolution image loading and stitching (Pillow only, no Qt)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def load_image(path: Path) -> Image.Image:
    """Load a scan at full resolution, honoring EXIF orientation, as RGB."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")



def stitch_images(front: Image.Image, back: Image.Image, direction: str) -> Image.Image:
    """Concatenate the back scan onto the front scan in the given direction.

    The back scan is proportionally scaled so the shared edge matches the
    front scan's edge; the front scan itself is never resampled, so it keeps
    its original resolution and sharpness.
    """
    direction = direction.lower()
    if direction not in ("top", "bottom", "left", "right"):
        raise ValueError(f"Unknown stitch direction: {direction!r}")

    f = front.convert("RGB")
    b = back.convert("RGB")

    if direction in ("top", "bottom"):
        if b.width != f.width:
            new_h = max(1, round(b.height * f.width / b.width))
            b = b.resize((f.width, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (f.width, f.height + b.height), "white")
        if direction == "top":
            canvas.paste(b, (0, 0))
            canvas.paste(f, (0, b.height))
        else:
            canvas.paste(f, (0, 0))
            canvas.paste(b, (0, f.height))
    else:
        if b.height != f.height:
            new_w = max(1, round(b.width * f.height / b.height))
            b = b.resize((new_w, f.height), Image.LANCZOS)
        canvas = Image.new("RGB", (f.width + b.width, f.height), "white")
        if direction == "left":
            canvas.paste(b, (0, 0))
            canvas.paste(f, (b.width, 0))
        else:
            canvas.paste(f, (0, 0))
            canvas.paste(b, (f.width, 0))
    return canvas


def orient_image(img: Image.Image, turns: int) -> Image.Image:
    """Rotate a PIL image by ``turns`` quarter-turns clockwise (lossless).

    Pure Pillow with no shared state: safe to call off the GUI thread.
    """
    for _ in range(turns % 4):
        img = img.transpose(Image.ROTATE_270)  # 90° clockwise, lossless
    return img

