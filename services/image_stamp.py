from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def stamp_datetime_on_photo(image_bytes: bytes, stamp_text: str) -> bytes:
    """Накладывает штамп даты/времени в правом нижнем углу фото."""
    with Image.open(BytesIO(image_bytes)) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        draw = ImageDraw.Draw(img)

        font_size = max(20, img.height // 24)
        font = None
        candidates = [
            "arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
        for c in candidates:
            try:
                font = ImageFont.truetype(c, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), stamp_text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        pad = max(12, img.width // 80)
        x = img.width - w - pad
        y = img.height - h - pad

        for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x + dx, y + dy), stamp_text, font=font, fill=(0, 0, 0))
        draw.text((x, y), stamp_text, font=font, fill=(255, 255, 255))

        out = BytesIO()
        img.save(out, format="JPEG", quality=95)
        return out.getvalue()
