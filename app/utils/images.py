import base64
import re
from io import BytesIO

from PIL import Image

DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.DOTALL)


def decode_image_data(data: str) -> Image.Image:
    raw = data.strip()
    match = DATA_URL_RE.match(raw)
    if match:
        payload = match.group("data")
    else:
        payload = raw

    image_bytes = base64.b64decode(payload)
    image = Image.open(BytesIO(image_bytes))
    return image.convert("RGBA")


def encode_image_data(image: Image.Image, fmt: str = "JPEG", quality: int = 88) -> str:
    buffer = BytesIO()
    if fmt.upper() == "JPEG":
        rgb = Image.new("RGB", image.size, (255, 255, 255))
        rgb.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
        rgb.save(buffer, format=fmt, quality=quality)
        mime = "image/jpeg"
    else:
        image.save(buffer, format=fmt)
        mime = f"image/{fmt.lower()}"

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
