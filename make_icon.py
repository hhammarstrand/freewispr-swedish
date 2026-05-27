"""Generate project-specific icons and social preview images."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
DOCS = ROOT / "docs"

INK = "#111827"
PANEL = "#fbfaf7"
LINE = "#e6e1d8"
BLUE = "#4f46e5"
YELLOW = "#facc15"
GREEN = "#11845b"
MUTED = "#667085"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _centered_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str,
                   font: ImageFont.ImageFont, fill: str) -> None:
    left, top, right, bottom = box
    text_box = draw.textbbox((0, 0), text, font=font)
    width = text_box[2] - text_box[0]
    height = text_box[3] - text_box[1]
    x = left + (right - left - width) / 2
    y = top + (bottom - top - height) / 2 - text_box[1]
    draw.text((x, y), text, font=font, fill=fill)


def make_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = size / 256
    radius = int(54 * scale)

    draw.rounded_rectangle([0, 0, size, size], radius=radius, fill=INK)
    draw.rounded_rectangle(
        [int(26 * scale), int(26 * scale), int(230 * scale), int(230 * scale)],
        radius=int(42 * scale),
        outline="#263244",
        width=max(1, int(2 * scale)),
    )

    cx = size / 2
    draw.rounded_rectangle(
        [cx - 28 * scale, 48 * scale, cx + 28 * scale, 128 * scale],
        radius=int(28 * scale),
        fill=PANEL,
    )
    draw.arc(
        [cx - 54 * scale, 86 * scale, cx + 54 * scale, 168 * scale],
        start=0,
        end=180,
        fill=PANEL,
        width=max(3, int(9 * scale)),
    )
    draw.line([cx, 166 * scale, cx, 190 * scale], fill=PANEL, width=max(3, int(9 * scale)))
    draw.line([cx - 34 * scale, 190 * scale, cx + 34 * scale, 190 * scale], fill=PANEL, width=max(3, int(9 * scale)))

    draw.rounded_rectangle(
        [32 * scale, 174 * scale, 96 * scale, 216 * scale],
        radius=int(17 * scale),
        fill=BLUE,
    )
    _centered_text(draw, (int(32 * scale), int(171 * scale), int(96 * scale), int(216 * scale)), "sv", _font(max(10, int(25 * scale)), True), "white")

    draw.rounded_rectangle(
        [160 * scale, 52 * scale, 214 * scale, 66 * scale],
        radius=int(7 * scale),
        fill=YELLOW,
    )
    draw.rounded_rectangle(
        [180 * scale, 32 * scale, 194 * scale, 86 * scale],
        radius=int(7 * scale),
        fill=YELLOW,
    )
    return img


def make_og_image() -> Image.Image:
    img = Image.new("RGB", (1200, 630), PANEL)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 1200, 630], fill=PANEL)
    for x in range(0, 1200, 48):
        draw.line([x, 0, x, 630], fill="#f0ece3", width=1)
    for y in range(0, 630, 48):
        draw.line([0, y, 1200, y], fill="#f0ece3", width=1)

    draw.rounded_rectangle([70, 70, 1130, 560], radius=48, fill="white", outline=LINE, width=2)
    draw.rounded_rectangle([106, 106, 232, 232], radius=34, fill=INK)
    icon = make_icon(126)
    img.paste(icon, (106, 106), icon)

    draw.rounded_rectangle([932, 116, 1058, 190], radius=24, fill="#f8fafc", outline=LINE, width=2)
    draw.text((959, 135), "åäö", font=_font(34, True), fill=BLUE)

    draw.text((106, 284), "freewispr-swedish", font=_font(72, True), fill=INK)
    draw.text((110, 372), "Svensk diktering för Windows", font=_font(38, False), fill=MUTED)

    chips = [
        ("lokal Whisper", GREEN),
        ("KBLab", BLUE),
        ("valfri LLM", INK),
    ]
    x = 110
    for text, color in chips:
        bbox = draw.textbbox((0, 0), text, font=_font(24, True))
        width = bbox[2] - bbox[0] + 42
        draw.rounded_rectangle([x, 458, x + width, 508], radius=25, fill="#f8fafc", outline=LINE, width=1)
        draw.ellipse([x + 18, 477, x + 30, 489], fill=color)
        draw.text((x + 42, 469), text, font=_font(24, True), fill=INK)
        x += width + 16

    draw.text((820, 486), "hhammarstrand.github.io", font=_font(22, False), fill=MUTED)
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 256]
    icon = make_icon(256)
    icon.save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(size, size) for size in sizes],
    )

    for size in [16, 32, 48, 64]:
        make_icon(size).save(DOCS / f"favicon-{size}.png")
    make_icon(256).save(DOCS / "apple-touch-icon.png")
    icon.save(
        DOCS / "favicon.ico",
        format="ICO",
        sizes=[(size, size) for size in sizes],
    )
    make_og_image().save(DOCS / "og-image.png")
    print("Generated assets/icon.ico and docs image assets.")


if __name__ == "__main__":
    main()
