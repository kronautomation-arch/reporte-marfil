"""Genera iconos cuadrados del dashboard a partir de assets/logo-marfil.png.

Centra el logo horizontal sobre un fondo blanco cuadrado con padding, y exporta
todos los tamanos que consume el PWA + favicon.
"""
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parents[2]
ASSETS = HERE / "assets"
LOGO = ASSETS / "logo-marfil.png"

# (nombre de salida, tamano px, padding relativo: % del canvas que queda libre a cada lado)
TARGETS = [
    ("favicon-16.png", 16, 0.08),
    ("favicon-32.png", 32, 0.08),
    ("apple-touch-icon.png", 180, 0.14),
    ("icon-192.png", 192, 0.14),
    ("icon-512.png", 512, 0.14),
]


def build_square_icon(logo: Image.Image, size: int, padding: float) -> Image.Image:
    """Pega el logo escalado a lo ancho (con padding) sobre fondo blanco cuadrado."""
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    max_w = int(size * (1 - padding * 2))
    scale = max_w / logo.width
    new_w = max_w
    new_h = max(1, int(logo.height * scale))
    # Si la altura escalada excede el alto disponible, re-escalamos por altura
    max_h = int(size * (1 - padding * 2))
    if new_h > max_h:
        scale = max_h / logo.height
        new_w = max(1, int(logo.width * scale))
        new_h = max_h
    resized = logo.resize((new_w, new_h), Image.LANCZOS)
    x = (size - new_w) // 2
    y = (size - new_h) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


def main() -> None:
    logo = Image.open(LOGO).convert("RGBA")
    print(f"Logo origen: {logo.size} ({LOGO})")
    for name, size, padding in TARGETS:
        out = build_square_icon(logo, size, padding)
        out.save(ASSETS / name, format="PNG", optimize=True)
        print(f"  -> {name}  {size}x{size}")
    print("Listo.")


if __name__ == "__main__":
    main()
