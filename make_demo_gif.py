"""Generate a zoomed demo GIF of the real dictation indicator flow.

The animation is a synthetic, reproducible close-up rather than a live screen
recording. Status labels, state colors, cursor offset, and equalizer bar
behavior mirror ``ui.indicator.FloatingIndicator`` and ``dictation.DictationMode``.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


OUT = Path("docs/freewispr-swedish-demo.gif")
WIDTH = 840
HEIGHT = 480
FPS = 12
FRAME_MS = round(1000 / FPS)
TOTAL_SECONDS = 7.6

# Colors copied from ui.styles / ui.indicator.
BG = "#111318"
BG2 = "#1a1d24"
BG3 = "#24272e"
FG = "#eaedf2"
FG2 = "#8891a0"
ACC = "#006aa7"
STATE_COLORS = {
    "listen": "#0080cc",
    "transcribe": "#f59e0b",
    "done": "#22c55e",
}

# FloatingIndicator constants, scaled because the GIF is an intentional close-up.
ZOOM = 1.85
NUM_BARS = 5
BAR_W = int(round(5 * ZOOM))
BAR_GAP = int(round(3 * ZOOM))
BAR_MIN = 3.0 * ZOOM
BAR_MAX = 20.0 * ZOOM
CANVAS_H = int(round(24 * ZOOM))
CURSOR_OFFSET_X = int(round(18 * ZOOM))
CURSOR_OFFSET_Y = int(round(18 * ZOOM))

SEQUENCE = [
    (0.0, 2.0, "Lyssnar…", "listen"),
    (2.0, 2.35, "Transkriberar…", "transcribe"),
    (2.35, 4.15, "Transkriberar lokalt…", "transcribe"),
    (4.15, 5.75, "LLM-granskar…", "transcribe"),
    (5.75, TOTAL_SECONDS, "Klistrad (LLM-polerad)", "done"),
]

PASTED_TEXT = "Sammanfatta ändringarna och föreslå nästa steg."


def _font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.ImageFont:
    font_dir = Path("C:/Windows/Fonts")
    candidates = []
    if mono:
        candidates.extend(["CascadiaMono.ttf", "CascadiaMono-SemiBold.ttf", "consola.ttf"])
    elif bold:
        candidates.extend(["segoeuib.ttf", "seguisb.ttf", "arialbd.ttf"])
    else:
        candidates.extend(["segoeui.ttf", "arial.ttf"])

    for name in candidates:
        path = font_dir / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                pass
    return ImageFont.load_default()


FONT_UI = _font(18)
FONT_UI_BOLD = _font(18, bold=True)
FONT_SMALL = _font(13)
FONT_MONO = _font(19, mono=True)
FONT_MONO_SMALL = _font(15, mono=True)
FONT_INDICATOR = _font(int(round(10 * ZOOM)), bold=True)


class IndicatorAnimator:
    def __init__(self) -> None:
        self.heights = [BAR_MIN] * NUM_BARS
        self.phase = 0
        self.last_state = ""

    def heights_for(self, t: float, state: str, frame_index: int) -> list[float]:
        if state != self.last_state:
            self.phase = 0
            self.last_state = state

        if state == "listen":
            level = 0.38 + 0.26 * math.sin(t * 8.0) + 0.16 * math.sin(t * 17.0)
            level = max(0.08, min(0.95, level))
            rng = random.Random(frame_index)
            for index in range(NUM_BARS):
                jitter = rng.uniform(0.3, 1.3)
                target = BAR_MIN + level * jitter * (BAR_MAX - BAR_MIN)
                target = max(BAR_MIN, min(BAR_MAX, target))
                current = self.heights[index]
                if target > current:
                    self.heights[index] = current * 0.2 + target * 0.8
                else:
                    self.heights[index] = current * 0.65 + target * 0.35
        elif state == "transcribe":
            self.phase += 1
            for index in range(NUM_BARS):
                wave = (math.sin(self.phase * 0.18 + index * 0.9) + 1) / 2
                self.heights[index] = BAR_MIN + wave * (BAR_MAX - BAR_MIN)
        else:
            self.heights = [BAR_MAX * 0.7] * NUM_BARS
        return self.heights


def _stage_at(t: float) -> tuple[str, str]:
    for start, end, label, state in SEQUENCE:
        if start <= t < end:
            return label, state
    return SEQUENCE[-1][2], SEQUENCE[-1][3]


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _rounded(draw: ImageDraw.ImageDraw, xy, radius: int, fill: str, outline: str | None = None) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline)


def _draw_terminal(draw: ImageDraw.ImageDraw, pasted: bool, caret_on: bool) -> None:
    x0, y0, x1, y1 = 28, 24, WIDTH - 28, HEIGHT - 28
    _rounded(draw, (x0, y0, x1, y1), 18, "#0b0f16", "#263142")
    _rounded(draw, (x0 + 1, y0 + 1, x1 - 1, y0 + 42), 18, "#151a23")
    draw.rectangle((x0 + 1, y0 + 24, x1 - 1, y0 + 43), fill="#151a23")

    for idx, color in enumerate(("#ff5f57", "#ffbd2e", "#28c840")):
        draw.ellipse((x0 + 18 + idx * 21, y0 + 16, x0 + 30 + idx * 21, y0 + 28), fill=color)

    draw.text((x0 + 92, y0 + 12), "codex", font=FONT_UI_BOLD, fill=FG)
    draw.text((x0 + 150, y0 + 14), "freewispr-swedish", font=FONT_SMALL, fill=FG2)

    tx = x0 + 34
    y = y0 + 72
    draw.text((tx, y), "PS C:\\GitHub\\freewispr-swedish> codex", font=FONT_MONO_SMALL, fill="#9fb3c8")
    y += 40
    draw.text((tx, y), "codex", font=FONT_MONO, fill="#dbeafe")
    draw.text((tx + 72, y + 3), "workspace: freewispr-swedish", font=FONT_MONO_SMALL, fill=FG2)
    y += 44
    draw.text((tx, y), "╭─", font=FONT_MONO, fill="#64748b")
    draw.text((tx + 44, y), "Vad vill du göra?", font=FONT_MONO, fill="#cbd5e1")
    y += 36
    draw.text((tx, y), "╰─>", font=FONT_MONO, fill="#64748b")
    prompt_x = tx + 54
    prompt_y = y
    if pasted:
        draw.text((prompt_x, prompt_y), PASTED_TEXT, font=FONT_MONO, fill=FG)
        text_w, _ = _text_size(draw, PASTED_TEXT, FONT_MONO)
        caret_x = prompt_x + text_w + 4
    else:
        draw.text((prompt_x, prompt_y), "", font=FONT_MONO, fill=FG)
        caret_x = prompt_x
    if caret_on:
        draw.rectangle((caret_x, prompt_y + 3, caret_x + 3, prompt_y + 25), fill="#93c5fd")

    draw.text((x0 + 34, y1 - 48), "Ctrl+Space hålls ned, tal släpps in i freewispr-swedish", font=FONT_SMALL, fill="#64748b")


def _draw_pointer(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    points = [
        (x, y),
        (x, y + 40),
        (x + 11, y + 30),
        (x + 19, y + 49),
        (x + 28, y + 45),
        (x + 20, y + 27),
        (x + 36, y + 27),
    ]
    shadow = [(px + 3, py + 3) for px, py in points]
    draw.polygon(shadow, fill="#000000")
    draw.polygon(points, fill="#f8fafc")
    draw.line(points + [points[0]], fill="#0f172a", width=2)


def _draw_indicator(
    base: Image.Image,
    label: str,
    state: str,
    bar_heights: list[float],
    cursor_x: int,
    cursor_y: int,
) -> None:
    scratch = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(scratch)
    text_w, text_h = _text_size(draw, label, FONT_INDICATOR)
    canvas_w = NUM_BARS * BAR_W + (NUM_BARS - 1) * BAR_GAP
    pad_x = int(round(16 * ZOOM))
    pad_y = int(round(9 * ZOOM))
    gap = int(round(12 * ZOOM))
    box_w = pad_x * 2 + canvas_w + gap + text_w
    box_h = max(CANVAS_H, text_h) + pad_y * 2
    x = cursor_x + CURSOR_OFFSET_X
    y = cursor_y + CURSOR_OFFSET_Y

    radius = int(round(10 * ZOOM))
    draw.rounded_rectangle((x + 4, y + 7, x + box_w + 4, y + box_h + 7), radius=radius, fill=(0, 0, 0, 95))
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=radius, fill=BG2, outline="#2b3240")

    color = STATE_COLORS[state]
    canvas_x = x + pad_x
    canvas_y = y + (box_h - CANVAS_H) // 2
    for index, height in enumerate(bar_heights):
        bx = canvas_x + index * (BAR_W + BAR_GAP)
        by = canvas_y + CANVAS_H - height
        draw.rounded_rectangle((bx, by, bx + BAR_W, canvas_y + CANVAS_H), radius=max(2, BAR_W // 2), fill=color)

    label_x = canvas_x + canvas_w + gap
    label_y = y + (box_h - text_h) // 2 - 2
    draw.text((label_x, label_y), label, font=FONT_INDICATOR, fill=FG)
    base.alpha_composite(scratch)


def make_frame(animator: IndicatorAnimator, frame_index: int) -> Image.Image:
    t = frame_index / FPS
    label, state = _stage_at(t)
    pasted = t >= 5.75
    caret_on = int(t * 2) % 2 == 0

    image = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    bg = Image.new("RGBA", (WIDTH, HEIGHT), "#0d1117")
    # Subtle vignette to make the close-up feel like a cropped screen capture.
    vignette = Image.new("L", (WIDTH, HEIGHT), 0)
    vignette_draw = ImageDraw.Draw(vignette)
    vignette_draw.ellipse((-120, -160, WIDTH + 120, HEIGHT + 170), fill=55)
    image = Image.composite(bg, image, vignette)

    draw = ImageDraw.Draw(image)
    _draw_terminal(draw, pasted=pasted, caret_on=caret_on)

    cursor_x = 432
    cursor_y = 268
    _draw_pointer(draw, cursor_x, cursor_y)

    bar_heights = animator.heights_for(t, state, frame_index)
    _draw_indicator(image, label, state, bar_heights, cursor_x, cursor_y)
    return image.convert("P", palette=Image.Palette.ADAPTIVE, colors=128)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    animator = IndicatorAnimator()
    frame_count = int(TOTAL_SECONDS * FPS)
    frames = [make_frame(animator, index) for index in range(frame_count)]
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
