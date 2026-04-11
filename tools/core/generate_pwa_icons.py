"""
Generador de iconos PWA para Marfil Dashboard.

Crea los iconos necesarios para que el dashboard se instale como app en iPhone:
- icon-192.png, icon-512.png   (PWA manifest)
- apple-touch-icon.png (180x180) (iOS home screen)
- favicon.png (32x32)            (browser tab)

Estilo: replica el badge del header del dashboard (fondo negro con "MARFIL" en
blanco, letter-spacing grande, esquinas redondeadas) + un punto verde en la
esquina superior derecha (live indicator).

Uso:
    python tools/core/generate_pwa_icons.py
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Colores del dashboard (var(--active) y var(--green-bright))
BG_COLOR = (17, 24, 39)        # #111827
TEXT_COLOR = (255, 255, 255)   # white
ACCENT_COLOR = (16, 185, 129)  # #10B981 (verde live-dot)

FONT_PATH = "C:/Windows/Fonts/arialbd.ttf"  # Arial Bold

# Salida en el root del proyecto (al lado de index.html)
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = OUTPUT_DIR / "assets"
ASSETS_DIR.mkdir(exist_ok=True)


def rounded_rect(size: int, radius_pct: float = 0.22) -> Image.Image:
    """Crea un canvas cuadrado con fondo negro y esquinas redondeadas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(size * radius_pct)
    draw.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=radius,
        fill=BG_COLOR,
    )
    return img


def draw_marfil_text(img: Image.Image):
    """Dibuja 'MARFIL' blanco centrado con letter-spacing grande + accent bar."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    text = "MARFIL"

    # Tamaño del texto: target ~60-65% del ancho (deja aire a los lados)
    # En vez de usar un font_size fijo, vamos a auto-fit: probamos tamaños
    # hasta que el ancho total quede en el rango deseado.
    target_width = int(w * 0.66)
    gap_ratio = 0.18  # gap entre letras como % del ancho de letra promedio

    # Busqueda binaria simple del font_size correcto
    font_size = int(w * 0.22)
    for _ in range(15):
        font = ImageFont.truetype(FONT_PATH, font_size)
        letter_widths = [font.getbbox(ch)[2] - font.getbbox(ch)[0] for ch in text]
        avg_w = sum(letter_widths) / len(letter_widths)
        gap = int(avg_w * gap_ratio)
        total_width = sum(letter_widths) + gap * (len(text) - 1)
        if abs(total_width - target_width) < w * 0.01:
            break
        font_size = int(font_size * target_width / total_width)

    # Medidas del texto (M no tiene descender)
    # getbbox del texto completo nos da el alto real del glifo mas ajustado
    m_bbox = font.getbbox("M")
    glyph_top = m_bbox[1]  # top del glifo (en coordenadas de baseline)
    glyph_bottom = m_bbox[3]
    text_height = glyph_bottom - glyph_top

    # Barra accent debajo del texto
    bar_w = int(total_width * 0.55)
    bar_h = max(2, int(h * 0.012))
    bar_gap = int(h * 0.04)  # espacio entre texto y barra

    # Grupo total: texto + gap + barra
    group_height = text_height + bar_gap + bar_h

    # Centrar el grupo vertical con ajuste optico: subimos 4% del alto
    # porque el texto bold es visualmente pesado arriba y la barra fina
    # abajo no compensa el "peso" visual.
    group_top = (h - group_height) // 2 - int(h * 0.04)

    # El texto empieza en group_top, pero tenemos que compensar el offset
    # que Pillow aplica con getbbox (el bbox[1] puede ser != 0 para el M)
    text_y = group_top - glyph_top

    # Dibujar letras una por una
    start_x = (w - total_width) // 2
    x = start_x
    for ch, lw in zip(text, letter_widths):
        bbox = font.getbbox(ch)
        draw.text((x - bbox[0], text_y), ch, font=font, fill=TEXT_COLOR)
        x += lw + gap

    # Barra verde inmediatamente debajo del texto
    bar_y = group_top + text_height + bar_gap
    bar_x = (w - bar_w) // 2
    draw.rounded_rectangle(
        [(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)],
        radius=bar_h // 2,
        fill=ACCENT_COLOR,
    )


def draw_accent_dot(img: Image.Image):
    """Punto verde 'live' en la esquina superior derecha (~8% del ancho)."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    dot_size = int(w * 0.08)
    margin = int(w * 0.14)
    x1 = w - margin - dot_size
    y1 = margin
    x2 = x1 + dot_size
    y2 = y1 + dot_size
    # Glow sutil (circulo mas grande con alpha bajo)
    glow_r = dot_size + int(dot_size * 0.6)
    glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    glow_draw.ellipse(
        [(cx - glow_r, cy - glow_r), (cx + glow_r, cy + glow_r)],
        fill=(*ACCENT_COLOR, 60),
    )
    img.alpha_composite(glow_layer)
    # Dot solido
    draw.ellipse([(x1, y1), (x2, y2)], fill=(*ACCENT_COLOR, 255))


def make_icon(size: int, with_accent: bool = True) -> Image.Image:
    """Genera un icono cuadrado completo."""
    # Trabajamos a 2x para antialiasing, luego downsample
    scale = 2
    work_size = size * scale
    img = rounded_rect(work_size, radius_pct=0.22)
    draw_marfil_text(img)
    # Downsample con lanczos para antialiasing suave
    return img.resize((size, size), Image.Resampling.LANCZOS)


def make_ios_icon(size: int = 180) -> Image.Image:
    """
    Icono para apple-touch-icon. iOS aplica su propia mascara de esquinas
    redondeadas, asi que aqui usamos cuadrado relleno (radius_pct=0).
    """
    scale = 2
    work_size = size * scale
    # Cuadrado lleno, sin transparencia (iOS aplica mascara)
    img = Image.new("RGBA", (work_size, work_size), (*BG_COLOR, 255))
    draw_marfil_text(img)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def save_icon(img: Image.Image, filename: str):
    path = ASSETS_DIR / filename
    img.save(path, format="PNG", optimize=True)
    print(f"  {filename:<28} {img.size[0]}x{img.size[1]}  {path.stat().st_size//1024}KB")


def main():
    print(f"Generando iconos en {ASSETS_DIR}:")
    # PWA manifest icons (rounded)
    save_icon(make_icon(192), "icon-192.png")
    save_icon(make_icon(512), "icon-512.png")
    save_icon(make_icon(1024), "icon-1024.png")  # para el preview en esta sesion
    # Apple touch icon (iOS aplica su mascara, usar cuadrado lleno)
    save_icon(make_ios_icon(180), "apple-touch-icon.png")
    # Favicon
    save_icon(make_icon(32, with_accent=False), "favicon-32.png")
    save_icon(make_icon(16, with_accent=False), "favicon-16.png")
    print()
    print("Listo.")


if __name__ == "__main__":
    main()
