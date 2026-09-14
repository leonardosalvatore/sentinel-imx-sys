#!/usr/bin/env python3
"""Compose the sentinel-imx-sys solution poster.

Neon '80s-synthwave one-pager telling the end-to-end story:
    train (host / Docker)  ->  deploy (SSH)  ->  run / detect (i.MX 8M Plus).

It renders docs/pipeline.dot with Graphviz (if the PNG is not already present),
then composites a title, the pipeline diagram, the real neon TUI screenshot, a
row of measured-metric "chips", and a footer onto a dark gradient canvas.

Outputs docs/sentinel-imx-solution.png. The PDF is produced by
scripts/make-diagram.sh via ImageMagick `convert`.

Only dependency is Pillow (plus `dot` on PATH). No network access.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
DOT_SRC = os.path.join(HERE, "pipeline.dot")
DIAGRAM_PNG = os.path.join(HERE, "pipeline.png")
TUI_PNG = os.path.join(HERE, "assets", "tui.png")
OUT_PNG = os.path.join(HERE, "sentinel-imx-solution.png")

# --------------------------------------------------------------------------- #
# palette (synthwave)
# --------------------------------------------------------------------------- #
BG_TOP = (26, 11, 46)       # deep purple
BG_BOTTOM = (6, 6, 21)      # near-black navy
CYAN = (0, 229, 255)
MAGENTA = (255, 47, 185)
GREEN = (57, 255, 20)
YELLOW = (255, 212, 0)
PURPLE = (178, 107, 255)
ORANGE = (255, 138, 0)
INK = (232, 232, 255)
DIM = (150, 150, 210)
GRID = (120, 40, 120)

W, H = 2600, 1700
MARGIN = 60

# --------------------------------------------------------------------------- #
# fonts
# --------------------------------------------------------------------------- #
FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
FONT_CANDIDATES_REG = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_CANDIDATES_MONO = [
    "/usr/share/fonts/pc/Px_TandyNew_Mono.ttf",           # retro DOS look
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def _load(cands, size):
    for path in cands:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def font_bold(size):
    return _load(FONT_CANDIDATES_BOLD, size)


def font_reg(size):
    return _load(FONT_CANDIDATES_REG, size)


def font_mono(size):
    return _load(FONT_CANDIDATES_MONO, size)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def ensure_diagram():
    """Render docs/pipeline.dot -> docs/pipeline.png if needed."""
    need = (not os.path.exists(DIAGRAM_PNG) or
            os.path.getmtime(DOT_SRC) > os.path.getmtime(DIAGRAM_PNG))
    if need:
        subprocess.run(
            ["dot", "-Tpng", "-Gdpi=170", DOT_SRC, "-o", DIAGRAM_PNG],
            check=True,
        )


def vertical_gradient(size, top, bottom):
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return base.resize((w, h))


def draw_perspective_grid(img):
    """A faint synthwave floor grid across the bottom."""
    grid = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(grid)
    horizon = int(H * 0.72)
    vanish_x = W // 2
    # horizontal lines, closer together near the horizon
    for i in range(1, 26):
        t = i / 25.0
        y = horizon + int((H - horizon) * (t ** 1.7))
        a = int(70 * (1 - t) + 12)
        d.line([(0, y), (W, y)], fill=GRID + (a,), width=2)
    # vertical lines converging to the vanishing point
    for gx in range(-14, 15):
        x_bottom = vanish_x + gx * (W // 12)
        a = 40
        d.line([(vanish_x, horizon), (x_bottom, H)], fill=GRID + (a,), width=2)
    grid = grid.filter(ImageFilter.GaussianBlur(0.6))
    img.alpha_composite(grid)


def paste_fit(canvas, im, box, align="center"):
    """Fit `im` into `box`=(x,y,w,h) preserving aspect; return placed rect."""
    x, y, bw, bh = box
    iw, ih = im.size
    scale = min(bw / iw, bh / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    im2 = im.resize((nw, nh), Image.LANCZOS)
    if align == "center":
        px = x + (bw - nw) // 2
        py = y + (bh - nh) // 2
    else:  # top-center
        px = x + (bw - nw) // 2
        py = y
    canvas.alpha_composite(im2.convert("RGBA"), (px, py))
    return (px, py, nw, nh)


def glow_text(canvas, xy, text, font, fill, glow, anchor="la", spacing=0,
              glow_radius=8):
    """Draw text with a colored glow. Supports letter-spacing via `spacing`."""
    tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    if spacing:
        _spaced_text(d, xy, text, font, glow + (255,), anchor, spacing)
    else:
        d.text(xy, text, font=font, fill=glow + (255,), anchor=anchor)
    blurred = tmp.filter(ImageFilter.GaussianBlur(glow_radius))
    canvas.alpha_composite(blurred)
    d2 = ImageDraw.Draw(canvas)
    if spacing:
        _spaced_text(d2, xy, text, font, fill + (255,), anchor, spacing)
    else:
        d2.text(xy, text, font=font, fill=fill + (255,), anchor=anchor)


def _spaced_text(draw, xy, text, font, fill, anchor, spacing):
    # measure total width with spacing
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    if anchor.startswith("m"):
        x -= total / 2
    elif anchor.startswith("r"):
        x -= total
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + spacing


def rounded_panel(canvas, box, border, radius=22, fill=(255, 255, 255, 14),
                  width=3):
    x, y, w, h = box
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                        fill=fill, outline=border + (255,), width=width)


def metric_chip(canvas, box, value, label, color):
    x, y, w, h = box
    # soft glow border
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle([x, y, x + w, y + h], radius=20,
                         outline=color + (255,), width=6)
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(7)))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([x, y, x + w, y + h], radius=20,
                        fill=(8, 7, 18, 245), outline=color + (255,),
                        width=3)
    vf = font_bold(64)
    lf = font_reg(25)
    # value (auto-shrink to fit)
    while d.textlength(value, font=vf) > w - 40 and vf.size > 28:
        vf = font_bold(vf.size - 3)
    # label (auto-shrink to fit within padding)
    while d.textlength(label, font=lf) > w - 28 and lf.size > 18:
        lf = font_reg(lf.size - 1)
    cx = x + w // 2
    d.text((cx, y + h * 0.42), value, font=vf, fill=color + (255,),
           anchor="mm")
    d.text((cx, y + h * 0.74), label, font=lf, fill=INK + (255,),
           anchor="mm")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ensure_diagram()

    canvas = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    draw_perspective_grid(canvas)

    d = ImageDraw.Draw(canvas)

    # ---- title -------------------------------------------------------------
    title_f = font_bold(96)
    glow_text(canvas, (MARGIN + 6, 42), "SENTINEL-IMX", title_f, CYAN, MAGENTA,
              anchor="la", spacing=10, glow_radius=12)
    sub_f = font_reg(38)
    d.text((MARGIN + 12, 158),
           "on-device log-anomaly detection  ·  NXP i.MX 8M Plus  ·  Vivante NPU",
           font=sub_f, fill=INK)
    # top-right kicker
    kick_f = font_mono(30)
    _spaced_text(d, (W - MARGIN, 60),
                 "TRAIN  →  DEPLOY  →  RUN", kick_f, MAGENTA + (255,),
                 "ra", 2)
    d.text((W - MARGIN, 108), "trained in Docker · shipped over SSH · scored on the NPU",
           font=font_reg(24), fill=DIM, anchor="ra")

    # divider line under header
    d.line([(MARGIN, 214), (W - MARGIN, 214)], fill=MAGENTA + (180,), width=3)

    # ---- layout regions ----------------------------------------------------
    body_top = 244
    body_bottom = H - 96
    left_x = MARGIN
    left_w = 1520
    right_x = left_x + left_w + 56
    right_w = W - MARGIN - right_x

    # ---- pipeline diagram (left) ------------------------------------------
    diagram = Image.open(DIAGRAM_PNG).convert("RGBA")
    paste_fit(canvas, diagram,
              (left_x, body_top, left_w, body_bottom - body_top),
              align="center")

    # ---- right column: screenshot + chips ---------------------------------
    # screenshot panel
    tui = Image.open(TUI_PNG).convert("RGBA")
    shot_h = int(right_w * tui.size[1] / tui.size[0])
    shot_box = (right_x, body_top, right_w, shot_h)
    # framed panel behind
    rounded_panel(canvas,
                  (right_x - 10, body_top - 10, right_w + 20, shot_h + 44),
                  MAGENTA, radius=18, fill=(20, 6, 30, 160), width=3)
    placed = paste_fit(canvas, tui, shot_box, align="top")
    cap_f = font_reg(24)
    d.text((right_x + right_w // 2, placed[1] + placed[3] + 8),
           "live neon TUI  ·  System Vitals · Vivante GC · Daemon · event stream",
           font=cap_f, fill=DIM, anchor="ma")

    # metrics header
    chips_top = body_top + shot_h + 70
    glow_text(canvas, (right_x, chips_top), "MEASURED ON THE BOARD",
              font_bold(34), GREEN, GREEN, anchor="la", glow_radius=6)

    # chips grid 3 x 2
    grid_top = chips_top + 58
    gap = 26
    cols = 3
    cw = (right_w - gap * (cols - 1)) // cols
    ch = (body_bottom - grid_top - gap) // 2
    chips = [
        ("0", "false positives · idle", GREEN),
        ("213-325", "anomaly loss (MSE)", MAGENTA),
        ("150", "calibrated threshold", YELLOW),
        ("~38%", "NPU load · Vivante c1", PURPLE),
        ("35 MB", "daemon RSS", CYAN),
        ("<1%", "CPU while parsing", ORANGE),
    ]
    for i, (val, lab, col) in enumerate(chips):
        r, c = divmod(i, cols)
        x = right_x + c * (cw + gap)
        y = grid_top + r * (ch + gap)
        metric_chip(canvas, (x, y, cw, ch), val, lab, col)

    # ---- footer ------------------------------------------------------------
    foot_f = font_mono(26)
    d.line([(MARGIN, H - 74), (W - MARGIN, H - 74)], fill=CYAN + (120,),
           width=2)
    d.text((MARGIN, H - 58),
           "github.com/leonardosalvatore/sentinel-imx-sys",
           font=foot_f, fill=CYAN)
    d.text((W - MARGIN, H - 58),
           "Apache-2.0  ·  libsystemd + TensorFlow Lite  ·  VX external delegate",
           font=foot_f, fill=DIM, anchor="ra")

    canvas.convert("RGB").save(OUT_PNG, "PNG")
    print(f"wrote {OUT_PNG}  ({W}x{H})")


if __name__ == "__main__":
    sys.exit(main())
