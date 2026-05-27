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
    """Flat modern mikrofon-ikon: gul mic på Sverigeblå rund bakgrund.

    Designprinciper:
    - Inga inre ramar eller dekorativa accenter (de blir grötiga vid 16px).
    - Solid cirkel istället för rounded rect — bättre på tray vid små storlekar.
    - Gul (Sverigeflaggans) mikrofon med generös padding så formen är
      igenkännbar även när tray-OS:et skalar ner till 16x16.
    - 4x supersampling: rita i 4x och nedskalera med LANCZOS för att slippa
      taggiga kurvor i mikrofonens båge.
    """
    ss = 4
    work = size * ss
    img = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Solid blå cirkel som bakgrund. En cirkel skalar bättre än rounded rect
    # vid <= 24px (rounded rect blir nästan kvadratisk pga aliasing).
    draw.ellipse([0, 0, work, work], fill=BLUE)

    # Mikrofon-proportioner (i 256-koordinatsystem, multipliceras med ss).
    cx = work / 2
    # Kapseln (mikrofonens kropp): smal, centrerad, ungefär 35% av höjden.
    cap_w = work * 0.22
    cap_top = work * 0.22
    cap_bot = work * 0.56
    draw.rounded_rectangle(
        [cx - cap_w / 2, cap_top, cx + cap_w / 2, cap_bot],
        radius=cap_w / 2,
        fill=YELLOW,
    )

    # U-formad arm (stativ-arc) under kapseln. Tjock kontur i samma gula färg.
    arc_w = work * 0.42
    arc_top = work * 0.42
    arc_bot = work * 0.72
    arc_thick = max(2, int(work * 0.045))
    draw.arc(
        [cx - arc_w / 2, arc_top, cx + arc_w / 2, arc_bot],
        start=0, end=180, fill=YELLOW, width=arc_thick,
    )

    # Stolpe från arc ner till basen.
    post_top = work * 0.69
    post_bot = work * 0.80
    draw.line([cx, post_top, cx, post_bot], fill=YELLOW, width=arc_thick)

    # Bas (horisontell linje under stolpen) — ger ikonen tydlig "stå-känsla".
    base_w = work * 0.22
    draw.line(
        [cx - base_w / 2, post_bot, cx + base_w / 2, post_bot],
        fill=YELLOW, width=arc_thick,
    )

    # Nedskala med LANCZOS för mjuka kanter.
    return img.resize((size, size), Image.LANCZOS)


def make_og_image() -> Image.Image:
    img = Image.new("RGB", (1200, 630), PANEL)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 1200, 630], fill=PANEL)
    draw.rounded_rectangle([78, 80, 1122, 550], radius=44, fill="#f6f3ed")
    draw.rounded_rectangle([72, 72, 1128, 540], radius=44, fill="white", outline=LINE, width=2)

    icon = make_icon(104)
    img.paste(icon, (116, 118), icon)
    draw.text((248, 122), "freewispr-swedish", font=_font(58, True), fill=INK)
    draw.text((252, 197), "Svensk diktering för Windows", font=_font(31, False), fill=MUTED)

    draw.line([116, 286, 662, 286], fill=LINE, width=2)
    draw.text((116, 335), "Lokal Whisper-transkribering", font=_font(31, True), fill=INK)
    draw.text((116, 383), "KBLab-modeller, terminalvänlig paste", font=_font(24, False), fill=MUTED)
    draw.text((116, 418), "och valfri LLM-granskning.", font=_font(24, False), fill=MUTED)

    labels = [("lokal först", GREEN), ("svenska modeller", BLUE), ("Windows", INK)]
    x = 116
    for text, color in labels:
        bbox = draw.textbbox((0, 0), text, font=_font(18, True))
        width = bbox[2] - bbox[0] + 42
        draw.rounded_rectangle([x, 470, x + width, 512], radius=21, fill="#f8fafc", outline=LINE, width=1)
        draw.ellipse([x + 16, 486, x + 27, 497], fill=color)
        draw.text((x + 38, 478), text, font=_font(18, True), fill=INK)
        x += width + 12

    draw.rounded_rectangle([756, 126, 1058, 454], radius=38, fill=SOFT, outline=LINE, width=2)
    draw.rounded_rectangle([802, 174, 1012, 224], radius=25, fill=INK)
    draw.ellipse([827, 192, 840, 205], fill=GREEN)
    draw.text((858, 187), "Lyssnar", font=_font(22, True), fill="white")

    bars = [18, 38, 28, 56, 34, 46, 22]
    bx = 828
    for height in bars:
        draw.rounded_rectangle([bx, 308 - height, bx + 13, 308], radius=7, fill=BLUE)
        bx += 22

    draw.rounded_rectangle([804, 346, 1010, 408], radius=20, fill="white", outline=LINE, width=1)
    draw.text((828, 361), "Transkriberar lokalt", font=_font(19, True), fill=INK)
    draw.text((828, 387), "Texten klistras in", font=_font(16, False), fill=MUTED)

    draw.text((792, 498), "hhammarstrand.github.io/freewispr-swedish", font=_font(18, False), fill=MUTED)
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
