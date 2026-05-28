"""
frontend/og-image.svg -> frontend/og-image.png (1200x630)
카톡/X/페북 미리보기에 PNG가 필요해서 빌드 스크립트로 분리.

svglib + reportlab 1차 시도, 폰트가 깨지면 Pillow로 직접 그리는 fallback 사용.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "frontend" / "og-image.svg"
PNG_PATH = ROOT / "frontend" / "og-image.png"
WIDTH, HEIGHT = 1200, 630


def render_with_pillow() -> None:
    from PIL import Image, ImageDraw, ImageFont

    PAPER = (250, 250, 247)
    PURPLE = (83, 74, 183)
    AMBER = (217, 119, 6)
    INK = (10, 10, 10)
    INK_SOFT = (61, 61, 61)
    INK_MUTED = (107, 107, 107)
    FACT_BLUE = (30, 64, 175)
    FACT_BLUE_FILL = (37, 99, 235)
    OPINION_DARK = (154, 52, 18)
    OPINION_FILL = (234, 88, 12)
    QUOTE_CYAN = (8, 145, 178)
    FRAME_DARK = (31, 41, 55)

    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)

    def radial_overlay(cx, cy, r, color, alpha_inner, falloff_stops):
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        steps = 60
        for i in range(steps, 0, -1):
            t = i / steps
            for stop_t, stop_a in falloff_stops:
                if t <= stop_t:
                    a = stop_a
                    break
            else:
                a = 0
            alpha = int(alpha_inner * a * (i / steps))
            rr = int(r * (i / steps))
            odraw.ellipse(
                (cx - rr, cy - rr, cx + rr, cy + rr),
                fill=(*color, alpha),
            )
        img.paste(overlay, (0, 0), overlay)

    purple_overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(purple_overlay)
    cx, cy = int(WIDTH * 0.85), int(HEIGHT * 0.20)
    rmax = int(WIDTH * 0.55)
    steps = 80
    for i in range(steps, 0, -1):
        t = i / steps
        rr = int(rmax * t)
        if t < 0.4:
            alpha = int(0.20 * 255 * (1 - t / 0.4) + 0.06 * 255 * (t / 0.4))
        elif t < 1.0:
            alpha = int(0.06 * 255 * (1 - (t - 0.4) / 0.6))
        else:
            alpha = 0
        pdraw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(*PURPLE, alpha))
    img.paste(purple_overlay, (0, 0), purple_overlay)

    amber_overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    adraw = ImageDraw.Draw(amber_overlay)
    cx, cy = int(WIDTH * 0.10), int(HEIGHT * 0.95)
    rmax = int(WIDTH * 0.50)
    for i in range(steps, 0, -1):
        t = i / steps
        rr = int(rmax * t)
        alpha = int(0.10 * 255 * (1 - t))
        adraw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(*AMBER, alpha))
    img.paste(amber_overlay, (0, 0), amber_overlay)

    draw = ImageDraw.Draw(img, "RGBA")

    def font(size: int, *, bold: bool = False, sl: bool = False):
        if bold:
            name = "malgunbd.ttf"
        elif sl:
            name = "malgunsl.ttf"
        else:
            name = "malgun.ttf"
        return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)

    draw.text((80, 88), "newslens", fill=INK, font=font(32, bold=True))
    draw.text((80, 137), "KOREAN NEWS MEDIA FILTER", fill=INK_MUTED, font=font(18, sl=True))

    headline = font(72, bold=True)

    # Line 1: "이 기사, 어디가 사실이고"
    line1_y = 220
    prefix1 = "이 기사, 어디가 "
    fact_text = "사실"
    suffix1 = "이고"
    px = 80
    draw.text((px, line1_y), prefix1, fill=INK, font=headline)
    prefix1_w = headline.getlength(prefix1)
    fact_w = headline.getlength(fact_text)
    fact_x = px + prefix1_w
    pad_x, pad_y = 12, 8
    draw.rounded_rectangle(
        (fact_x - pad_x, line1_y - pad_y, fact_x + fact_w + pad_x, line1_y + 76 + pad_y),
        radius=6,
        fill=(*FACT_BLUE_FILL, 46),
    )
    draw.text((fact_x, line1_y), fact_text, fill=FACT_BLUE, font=headline)
    draw.text((fact_x + fact_w, line1_y), suffix1, fill=INK, font=headline)

    # Line 2: "어디가 의견인지"
    line2_y = 320
    prefix2 = "어디가 "
    opinion_text = "의견"
    suffix2 = "인지"
    draw.text((px, line2_y), prefix2, fill=INK, font=headline)
    prefix2_w = headline.getlength(prefix2)
    opinion_w = headline.getlength(opinion_text)
    opinion_x = px + prefix2_w
    draw.rounded_rectangle(
        (opinion_x - pad_x, line2_y - pad_y, opinion_x + opinion_w + pad_x, line2_y + 76 + pad_y),
        radius=6,
        fill=(*OPINION_FILL, 46),
    )
    draw.text((opinion_x, line2_y), opinion_text, fill=OPINION_DARK, font=headline)
    draw.text((opinion_x + opinion_w, line2_y), suffix2, fill=INK, font=headline)

    # Line 3
    draw.text((80, 420), "색깔로 보여드립니다.", fill=INK, font=headline)

    # Legend
    legend_y = 560
    legend = font(20, sl=True)
    items = [
        ("사실", FACT_BLUE_FILL),
        ("인용", QUOTE_CYAN),
        ("의견", OPINION_FILL),
        ("프레이밍", FRAME_DARK),
    ]
    x = 80
    for label, color in items:
        draw.ellipse((x, legend_y, x + 20, legend_y + 20), fill=color)
        draw.text((x + 32, legend_y - 2), label, fill=INK_SOFT, font=legend)
        x += int(legend.getlength(label)) + 80

    # Bottom-right brand
    brand_small = font(18, sl=True)
    brand_w = brand_small.getlength("newslens")
    draw.text((WIDTH - 80 - brand_w, HEIGHT - 45), "newslens", fill=INK_MUTED, font=brand_small)

    img.save(PNG_PATH, "PNG", optimize=True)
    print(f"[pillow] wrote {PNG_PATH} ({PNG_PATH.stat().st_size:,} bytes)")


def main() -> int:
    if not SVG_PATH.exists():
        print(f"error: {SVG_PATH} not found", file=sys.stderr)
        return 1
    render_with_pillow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
