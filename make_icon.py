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
BLUE = "#006AA7"
YELLOW = "#FECC02"
GREEN = "#11845b"
MUTED = "#667085"
SOFT = "#f2efe8"


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

    draw.rounded_rectangle([160 * scale, 40 * scale, 216 * scale, 54 * scale], radius=int(7 * scale), fill=YELLOW)
    draw.rounded_rectangle([160 * scale, 62 * scale, 198 * scale, 76 * scale], radius=int(7 * scale), fill=BLUE)
    return img


def make_og_image() -> Image.Image:
    img = Image.new("RGB", (1200, 630), PANEL)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 1200, 630], fill=PANEL)
    draw.rounded_rectangle([72, 72, 1128, 558], radius=46, fill="white", outline=LINE, width=2)

    icon = make_icon(112)
    img.paste(icon, (116, 118), icon)
    draw.text((252, 128), "freewispr-swedish", font=_font(56, True), fill=INK)
    draw.text((256, 202), "Svensk diktering för Windows", font=_font(31, False), fill=MUTED)

    draw.line([116, 292, 650, 292], fill=LINE, width=2)
    draw.text((116, 342), "Lokal Whisper-transkribering", font=_font(29, True), fill=INK)
    draw.text((116, 388), "KBLab-modeller, terminalvänlig paste och valfri LLM.", font=_font(24, False), fill=MUTED)

    labels = [("lokal först", GREEN), ("svenska modeller", BLUE), ("Windows", INK)]
    x = 116
    for text, color in labels:
        bbox = draw.textbbox((0, 0), text, font=_font(19, True))
        width = bbox[2] - bbox[0] + 38
        draw.rounded_rectangle([x, 468, x + width, 510], radius=21, fill="#f8fafc", outline=LINE, width=1)
        draw.ellipse([x + 16, 484, x + 26, 494], fill=color)
        draw.text((x + 36, 477), text, font=_font(19, True), fill=INK)
        x += width + 12

    draw.rounded_rectangle([768, 132, 1058, 468], radius=34, fill=SOFT, outline=LINE, width=2)
    draw.rounded_rectangle([804, 174, 1022, 224], radius=25, fill=INK)
    draw.ellipse([828, 192, 840, 204], fill=GREEN)
    draw.text((858, 187), "Lyssnar", font=_font(22, True), fill="white")

    bars = [16, 34, 22, 46, 26, 38, 18]
    bx = 828
    for height in bars:
        draw.rounded_rectangle([bx, 300 - height, bx + 12, 300], radius=6, fill=BLUE)
        bx += 22

    draw.rounded_rectangle([804, 338, 1022, 410], radius=20, fill="white", outline=LINE, width=1)
    draw.text((828, 355), "Transkriberar lokalt", font=_font(20, True), fill=INK)
    draw.text((828, 382), "Klistrad", font=_font(18, False), fill=MUTED)

    draw.text((816, 502), "hhammarstrand.github.io/freewispr-swedish", font=_font(18, False), fill=MUTED)
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
