#!/usr/bin/env python3
"""Render the sentinel-imx-sys technical brief as a multi-page PDF.

    "Why standard log parsing fails on embedded boards -
     and why a custom on-device anomaly-detection model is the better fix."

Neon '80s-synthwave styling to match the solution poster. Pure Pillow: each page
is composited as an image and the pages are saved together as a single PDF
(Image.save(..., save_all=True)). Page PNGs are also dropped in /tmp for preview.

Only dependency is Pillow. No network. Reuses docs/pipeline.png if present.

    python3 docs/make_whitepaper.py
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
DIAGRAM_PNG = os.path.join(HERE, "pipeline.png")
OUT_PDF = os.path.join(HERE, "why-on-device-anomaly-detection.pdf")
PREVIEW_DIR = "/tmp"

# --------------------------------------------------------------------------- #
# page geometry (A4 portrait @ ~150 dpi)
# --------------------------------------------------------------------------- #
W, H = 1240, 1754
MARGIN = 100
COL_W = W - 2 * MARGIN

# --------------------------------------------------------------------------- #
# palette
# --------------------------------------------------------------------------- #
BG_TOP = (22, 12, 40)
BG_BOTTOM = (6, 6, 18)
CYAN = (0, 229, 255)
MAGENTA = (255, 47, 185)
GREEN = (57, 255, 20)
YELLOW = (255, 212, 0)
PURPLE = (178, 107, 255)
ORANGE = (255, 138, 0)
RED = (255, 80, 96)
INK = (226, 226, 245)
BODY = (198, 200, 224)
DIM = (150, 150, 200)
GRID = (120, 40, 120)

# --------------------------------------------------------------------------- #
# fonts
# --------------------------------------------------------------------------- #
BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
REG = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
MONO = ["/usr/share/fonts/pc/Px_TandyNew_Mono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]


def _load(cands, size):
    for p in cands:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def fb(s):
    return _load(BOLD, s)


def fr(s):
    return _load(REG, s)


def fm(s):
    return _load(MONO, s)


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def gradient(size, top, bottom):
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


def floor_grid(img, from_y):
    grid = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(grid)
    vx = W // 2
    n = 18
    for i in range(1, n + 1):
        t = i / n
        y = from_y + int((H - from_y) * (t ** 1.7))
        a = int(60 * (1 - t) + 10)
        d.line([(0, y), (W, y)], fill=GRID + (a,), width=2)
    for gx in range(-10, 11):
        xb = vx + gx * (W // 9)
        d.line([(vx, from_y), (xb, H)], fill=GRID + (35,), width=2)
    img.alpha_composite(grid.filter(ImageFilter.GaussianBlur(0.6)))


def glow_text(canvas, xy, text, font, fill, glow, anchor="la", spacing=0,
              radius=8):
    tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    _text(d, xy, text, font, glow + (255,), anchor, spacing)
    canvas.alpha_composite(tmp.filter(ImageFilter.GaussianBlur(radius)))
    _text(ImageDraw.Draw(canvas), xy, text, font, fill + (255,), anchor, spacing)


def _text(draw, xy, text, font, fill, anchor="la", spacing=0):
    if not spacing:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
        return
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    if anchor.startswith("m"):
        x -= total / 2
    elif anchor.startswith("r"):
        x -= total
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + spacing


def wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def paragraph(draw, xy, text, font, fill, max_w, leading=10):
    x, y = xy
    for ln in wrap(draw, text, font, max_w):
        draw.text((x, y), ln, font=font, fill=fill)
        asc, desc = font.getmetrics()
        y += asc + desc + leading
    return y


def bullet(draw, x, y, max_w, head, body, color, hf, bf):
    """Neon square bullet, bold head + wrapped body. Returns new y."""
    sq = 16
    draw.rounded_rectangle([x, y + 8, x + sq, y + 8 + sq], radius=3,
                           fill=color + (255,))
    tx = x + sq + 20
    tw = max_w - (sq + 20)
    # head + body flow as one block; head is bold and colored
    if head:
        draw.text((tx, y), head, font=hf, fill=color + (255,))
        asc, desc = hf.getmetrics()
        y += asc + desc + 4
    y = paragraph(draw, (tx, y), body, bf, BODY, tw, leading=8)
    return y + 14


# --------------------------------------------------------------------------- #
# page furniture
# --------------------------------------------------------------------------- #
def new_page(grid_from=None):
    img = gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    if grid_from is not None:
        floor_grid(img, grid_from)
    return img


def kicker(canvas, text):
    d = ImageDraw.Draw(canvas)
    _text(d, (MARGIN, 70), text, fm(24), MAGENTA + (255,), "la", 3)
    d.line([(MARGIN, 108), (W - MARGIN, 108)], fill=MAGENTA + (150,), width=2)


def heading(canvas, y, text, color=CYAN):
    d = ImageDraw.Draw(canvas)
    glow_text(canvas, (MARGIN, y), text, fb(40), color, color, radius=6)
    asc, desc = fb(40).getmetrics()
    yb = y + asc + desc + 8
    d.line([(MARGIN, yb), (MARGIN + 120, yb)], fill=MAGENTA + (255,), width=4)
    return yb + 26


def footer(canvas, page_no, total):
    d = ImageDraw.Draw(canvas)
    d.line([(MARGIN, H - 84), (W - MARGIN, H - 84)], fill=CYAN + (110,),
           width=2)
    d.text((MARGIN, H - 66), "leonardosalvatore/sentinel-imx-sys",
           font=fm(18), fill=CYAN)
    d.text((W // 2, H - 66), f"{page_no} / {total}", font=fm(18), fill=DIM,
           anchor="ma")
    d.text((W - MARGIN, H - 66), "Technical brief  ·  Apache-2.0",
           font=fm(18), fill=DIM, anchor="ra")


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
def page_cover():
    c = new_page(grid_from=int(H * 0.60))
    d = ImageDraw.Draw(c)
    _text(d, (MARGIN, 150), "SENTINEL-IMX  ·  TECHNICAL BRIEF", fm(26),
          CYAN + (255,), "la", 3)

    ty = 250
    for line, col in [("Why standard log parsing", INK),
                      ("fails on embedded boards", INK)]:
        glow_text(c, (MARGIN, ty), line, fb(72), col, MAGENTA, radius=10)
        ty += 92
    ty += 18
    glow_text(c, (MARGIN, ty),
              "...and why a custom on-device model fixes it",
              fb(40), CYAN, CYAN, radius=6)
    ty += 96

    blurb = ("Embedded boards emit a relentless stream of kernel and system "
             "logs. The usual answers - regex/keyword rules or shipping every "
             "line to a cloud stack - are brittle, noisy, network-hungry, and "
             "blind to the failures nobody wrote a rule for yet. This brief "
             "explains why, and makes the case for a tiny anomaly-detection "
             "model that learns what 'normal' looks like for your specific "
             "device and runs entirely on its NPU.")
    ty = paragraph(d, (MARGIN, ty), blurb, fr(28), BODY, COL_W, leading=12)

    # pipeline thumbnail
    if os.path.exists(DIAGRAM_PNG):
        dia = Image.open(DIAGRAM_PNG).convert("RGBA")
        scale = min(COL_W / dia.size[0], 560 / dia.size[1])
        nw, nh = int(dia.size[0] * scale), int(dia.size[1] * scale)
        dia = dia.resize((nw, nh), Image.LANCZOS)
        px = MARGIN + (COL_W - nw) // 2
        py = ty + 24
        c.alpha_composite(dia, (px, py))
        d.text((W // 2, py + nh + 8),
               "the sentinel-imx-sys pipeline: train on host -> deploy over SSH "
               "-> detect on the NPU",
               font=fr(20), fill=DIM, anchor="ma")

    footer(c, 1, TOTAL)
    return c


def page_problem():
    c = new_page()
    kicker(c, "THE PROBLEM")
    d = ImageDraw.Draw(c)
    y = heading(c, 140, "Standard log parsing does not fit the edge")

    y = paragraph(d, (MARGIN, y),
                  "Two approaches dominate today, and both struggle on a "
                  "constrained, remote, device-specific board:",
                  fr(26), INK, COL_W, leading=10)
    y += 16

    items = [
        ("Rules only catch what you already predicted.",
         "Regex and keyword alerts fire only for failure modes someone "
         "anticipated and hand-coded. Embedded systems fail in device- and "
         "firmware-specific ways, so the unknown-unknowns - the incidents you "
         "most want to catch - sail straight through.", RED),
        ("Rules rot with every update.",
         "Each BSP, kernel, or driver bump changes log wording and format. "
         "Rule sets silently break and demand endless re-tuning and "
         "maintenance that does not scale across fleets or releases.", ORANGE),
        ("Alert fatigue drowns the real signal.",
         "Threshold and keyword rules light up on benign chatter. Operators "
         "mute noisy alerts - and the one message that mattered is muted with "
         "them.", YELLOW),
        ("'Normal' is device-specific; static rules are not.",
         "A line that is perfectly routine on one unit is a red flag on "
         "another. One-size-fits-all rules cannot encode a per-device notion "
         "of healthy behavior.", MAGENTA),
        ("The cloud is the wrong place to decide.",
         "Shipping logs to ELK/Loki assumes bandwidth, connectivity, and power "
         "the edge often lacks, and it adds latency, running cost, and data "
         "sovereignty / privacy problems. A board cannot react in real time if "
         "the verdict lives in a datacenter.", PURPLE),
        ("Heavy agents, blind to novelty.",
         "Full log-processing agents (Logstash, Fluentd) are large for a "
         "board's CPU, RAM, and flash budget - and still never flag a genuinely "
         "new fault or a slow degradation until a human writes a rule after the "
         "outage.", CYAN),
    ]
    hf, bf = fb(27), fr(24)
    for head, body, col in items:
        y = bullet(d, MARGIN, y, COL_W, head, body, col, hf, bf)

    footer(c, 2, TOTAL)
    return c


def page_solution():
    c = new_page()
    kicker(c, "A BETTER APPROACH")
    d = ImageDraw.Draw(c)
    y = heading(c, 140, "Learn 'normal' on the device, flag the rest",
                color=GREEN)

    y = paragraph(d, (MARGIN, y),
                  "Instead of enumerating everything that can go wrong, train a "
                  "small autoencoder on the board's own normal logs. It "
                  "reconstructs familiar patterns well and unfamiliar ones "
                  "poorly - so a high reconstruction error flags novelty you "
                  "never had to anticipate. It runs entirely on the Vivante "
                  "NPU.",
                  fr(26), INK, COL_W, leading=10)
    y += 18

    items = [
        ("No rules to write - it learns from real traffic.",
         "A capture-first workflow records the device's own logs; you train "
         "from them. The model encodes what healthy looks like for this exact "
         "unit.", GREEN),
        ("Catches the unknown.",
         "Reconstruction error surfaces novel anomalies and slow drift, not "
         "just pre-listed keywords.", CYAN),
        ("Fully on-device and offline.",
         "No cloud, no log shipping: data stays local (privacy + sovereignty) "
         "and the board reacts in real time.", PURPLE),
        ("Tiny footprint.",
         "An INT8-quantized model on the NPU costs under 1% CPU and about "
         "35 MB RSS, leaving the CPU free for the real workload.", YELLOW),
        ("Low maintenance.",
         "After a BSP or kernel change, re-capture a fresh baseline and "
         "retrain - no rule archaeology.", ORANGE),
        ("Noise-resistant by design, and actionable.",
         "Log templating plus L2-normalized feature hashing score events by "
         "pattern novelty (not line length or PID churn), and each anomaly "
         "runs your own script: LED, service restart, or notify.", MAGENTA),
    ]
    hf, bf = fb(27), fr(24)
    for head, body, col in items:
        y = bullet(d, MARGIN, y, COL_W, head, body, col, hf, bf)

    footer(c, 3, TOTAL)
    return c


def page_compare():
    c = new_page()
    kicker(c, "SIDE BY SIDE")
    y = heading(c, 140, "Rule-based / cloud vs on-device model")

    d = ImageDraw.Draw(c)
    rows = [
        ("Unknown failures", "Missed - known patterns only",
         "Detected via reconstruction error"),
        ("Maintenance", "Rewrite rules every update",
         "Recapture + retrain a baseline"),
        ("Connectivity", "Needs network / cloud",
         "Fully offline, on-device"),
        ("Time to act", "Round-trip to a datacenter",
         "Real-time, local"),
        ("Data privacy", "Logs leave the device",
         "Data stays on the device"),
        ("Footprint", "Heavy log agents",
         "INT8 model, <1% CPU, ~35 MB"),
        ("Notion of normal", "One static rule set",
         "Learned per device"),
    ]

    x0 = MARGIN
    col1 = 250
    col2 = 405
    col3 = COL_W - col1 - col2
    row_h = 118
    top = y + 6

    hf = fb(23)
    # header row
    d.rounded_rectangle([x0, top, x0 + COL_W, top + 70], radius=12,
                        fill=(10, 8, 22, 255), outline=CYAN + (255,), width=2)
    d.text((x0 + 24, top + 22), "Dimension", font=hf, fill=INK)
    d.text((x0 + col1 + 24, top + 22), "Rule-based / cloud parsing", font=hf,
           fill=RED + (255,))
    d.text((x0 + col1 + col2 + 24, top + 22),
           "On-device model (sentinel-imx)", font=hf, fill=GREEN + (255,))
    ry = top + 70 + 14

    lf = fb(24)
    cf = fr(23)
    for i, (dim, bad, good) in enumerate(rows):
        d.rounded_rectangle([x0, ry, x0 + COL_W, ry + row_h - 12], radius=12,
                            fill=(8, 7, 18, 245),
                            outline=(90, 90, 140, 255), width=2)
        # vertical separators
        d.line([(x0 + col1, ry + 10), (x0 + col1, ry + row_h - 22)],
               fill=(80, 80, 120, 255), width=1)
        d.line([(x0 + col1 + col2, ry + 10),
                (x0 + col1 + col2, ry + row_h - 22)],
               fill=(80, 80, 120, 255), width=1)
        paragraph(d, (x0 + 24, ry + 20), dim, lf, INK, col1 - 40, leading=6)
        # bad cell with a dim red dot
        d.ellipse([x0 + col1 + 22, ry + 26, x0 + col1 + 22 + 14,
                   ry + 26 + 14], fill=RED + (255,))
        paragraph(d, (x0 + col1 + 48, ry + 20), bad, cf, BODY, col2 - 70,
                  leading=6)
        d.ellipse([x0 + col1 + col2 + 22, ry + 26,
                   x0 + col1 + col2 + 22 + 14, ry + 26 + 14],
                  fill=GREEN + (255,))
        paragraph(d, (x0 + col1 + col2 + 48, ry + 20), good, cf, BODY,
                  col3 - 70, leading=6)
        ry += row_h

    footer(c, 4, TOTAL)
    return c


def page_result():
    c = new_page(grid_from=int(H * 0.66))
    kicker(c, "IN PRACTICE")
    d = ImageDraw.Draw(c)
    y = heading(c, 140, "How sentinel-imx-sys delivers it", color=PURPLE)

    y = paragraph(d, (MARGIN, y),
                  "The daemon listens to the systemd journal (kernel + "
                  "userspace logs) and the D-Bus system bus, "
                  "sanitizes each line into a stable template, encodes it into "
                  "an INT8 [1,64] vector, and scores it with the autoencoder on "
                  "the Vivante NPU. You train on your computer inside Docker, "
                  "deploy over SSH with one script, and detection then runs "
                  "on-device - no cloud in the loop.",
                  fr(26), INK, COL_W, leading=10)
    y += 20

    glow_text(c, (MARGIN, y), "MEASURED ON THE BOARD", fb(30), GREEN, GREEN,
              radius=5)
    y += 66

    chips = [
        ("0", "false positives - idle", GREEN),
        ("213-325", "anomaly loss (MSE)", MAGENTA),
        ("150", "calibrated threshold", YELLOW),
        ("~38%", "NPU load - Vivante c1", PURPLE),
        ("35 MB", "daemon RSS", CYAN),
        ("<1%", "CPU while parsing", ORANGE),
    ]
    cols = 3
    gap = 26
    cw = (COL_W - gap * (cols - 1)) // cols
    ch = 150
    for i, (val, lab, col) in enumerate(chips):
        r, cc = divmod(i, cols)
        x = MARGIN + cc * (cw + gap)
        yy = y + r * (ch + gap)
        glow = Image.new("RGBA", c.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle([x, yy, x + cw, yy + ch],
                                               radius=18,
                                               outline=col + (255,), width=5)
        c.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6)))
        d.rounded_rectangle([x, yy, x + cw, yy + ch], radius=18,
                            fill=(8, 7, 18, 245), outline=col + (255,),
                            width=3)
        vf = fb(52)
        while d.textlength(val, font=vf) > cw - 36 and vf.size > 26:
            vf = fb(vf.size - 3)
        d.text((x + cw // 2, yy + ch * 0.40), val, font=vf,
               fill=col + (255,), anchor="mm")
        d.text((x + cw // 2, yy + ch * 0.74), lab, font=fr(22), fill=INK,
               anchor="mm")
    y += 2 * ch + gap + 40

    # takeaway box
    box_h = 190
    d.rounded_rectangle([MARGIN, y, W - MARGIN, y + box_h], radius=18,
                        fill=(14, 10, 26, 245), outline=GREEN + (255,),
                        width=3)
    d.text((MARGIN + 28, y + 22), "The takeaway", font=fb(28),
           fill=GREEN + (255,))
    paragraph(d, (MARGIN + 28, y + 72),
              "You get proactive, private, low-cost health monitoring at the "
              "edge that improves as it sees more of the device's real life - "
              "catching the failures a rule set never anticipated, without "
              "sending a single log line off the board.",
              fr(25), BODY, COL_W - 56, leading=8)

    footer(c, 5, TOTAL)
    return c


TOTAL = 5


def main():
    pages = [page_cover(), page_problem(), page_solution(), page_compare(),
             page_result()]
    rgb = [p.convert("RGB") for p in pages]
    rgb[0].save(OUT_PDF, "PDF", resolution=150.0, save_all=True,
                append_images=rgb[1:])
    for i, p in enumerate(rgb, 1):
        p.save(os.path.join(PREVIEW_DIR, f"brief_page_{i}.png"))
    print(f"wrote {OUT_PDF}  ({TOTAL} pages)")


if __name__ == "__main__":
    sys.exit(main())
