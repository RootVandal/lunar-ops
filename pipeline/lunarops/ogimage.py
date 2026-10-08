"""Social preview card (web/og.png, 1200 x 630) drawn from the real results.

The strip is the actual site x date map for a two-week mission (sunlight >= 70 %,
DTE >= 50 %, blackout <= 24 h, panels 1 m), computed with the reference solver.

    python -m lunarops.ogimage
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .paths import WEB_DATA
from .solver import Requirements, SiteSeries, evaluate, window_metrics

W, H = 1200, 630
DEEP, ELECTRIC, YONDER, YELLOW, INK, INK2, LINE = "#07173F", "#0042A6", "#2E96F5", "#EAFE07", "#EEF3FF", "#9DB0D8", "#1D3B7C"
FAIL = "#1A2E66"
FONTS = Path("C:/Windows/Fonts")


def font(names, size):
    for n in names:
        for p in (FONTS / n, Path("/usr/share/fonts/truetype/dejavu") / n):
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def series(meta, s, h=0):
    n, nh = meta["grid"]["n"], len(meta["heights_m"])
    u8 = np.fromfile(WEB_DATA / f"site_{s['id']}.bin", np.uint8, count=2 * nh * n)
    f = u8[h * n:(h + 1) * n] / meta["f_scale"]
    dte = (u8[(nh + h) * n:(nh + h + 1) * n] & 1).astype(bool)
    return SiteSeries(s["id"], meta["grid"]["start_utc"], meta["grid"]["step_s"], f.astype(float), dte)


def main():
    meta = json.loads((WEB_DATA / "sites.json").read_text())
    req = Requirements(duration_h=14 * 24, min_sun_pct=70, min_dte_pct=50, max_blackout_h=24)
    tables = evaluate([window_metrics(series(meta, s), req) for s in meta["sites"]], req)
    day = int(86400 / meta["grid"]["step_s"])

    img = Image.new("RGB", (W, H), DEEP)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 48):                                   # coordinate grid, screened back
        d.line([(x, 0), (x, H)], fill="#0B2152")
    for y in range(0, H, 48):
        d.line([(0, y), (W, y)], fill="#0B2152")
    for i in range(H):                                          # Electric Blue -> Deep Blue band at the top
        if i > 210:
            break
        a = 1 - i / 210
        c = tuple(int(int(DEEP[k:k + 2], 16) * (1 - a * .6) + int(ELECTRIC[k:k + 2], 16) * a * .6) for k in (1, 3, 5))
        d.line([(0, i), (W, i)], fill=c)

    big = font(["bahnschrift.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"], 92)
    mid = font(["bahnschrift.ttf", "arial.ttf", "DejaVuSans.ttf"], 34)
    small = font(["consola.ttf", "DejaVuSansMono.ttf"], 20)
    x0 = 64
    d.text((x0, 52), "LUNAR", font=big, fill=INK)
    wl = d.textlength("LUNAR", font=big)
    d.text((x0 + wl, 52), "//", font=big, fill=YELLOW)
    d.text((x0 + wl + d.textlength("//", font=big), 52), "OPS", font=big, fill=INK)
    d.text((x0, 160), "Where and when can a CLPS lander work at the lunar south pole?", font=mid, fill=INK)
    d.text((x0, 208), "Requirements in  →  feasible sites & dates, why the rest fail, how robust the answer is", font=small, fill=INK2)

    # the real site x date map
    top, left, right, row = 270, 250, W - 64, 40
    names = [s.get("region") or s["name"] for s in meta["sites"]]
    names = ["IM-2 site" if s["id"] == "im2-athena" else nm for s, nm in zip(meta["sites"], names)]
    lab = font(["bahnschrift.ttf", "arial.ttf", "DejaVuSans.ttf"], 22)
    for r, (t, nm) in enumerate(zip(tables, names)):
        y = top + r * row
        d.text((left - 18 - d.textlength(nm, font=lab), y + 8), nm, font=lab, fill=INK)
        n_days = int(np.ceil((t.starts[-1] + 1) / day))
        ok = np.zeros(n_days, bool)
        ok[(t.starts[t.feasible] // day)] = True
        cw = (right - left) / n_days
        for k in range(n_days):
            d.rectangle([left + k * cw, y + 5, left + (k + 1) * cw - 0.2, y + row - 5], fill=YELLOW if ok[k] else FAIL)
    d.text((left, top + 6 * row + 10), "Every landing day of 2027–2028 · yellow = a 14-day mission works", font=small, fill=INK2)
    d.text((x0, H - 52), "NASA LOLA terrain · NAIF SPICE · DSN ≥ 6° · validated against JPL Horizons and NASA GSFC", font=small, fill=YONDER)
    d.rectangle([0, 0, 14, 14], outline=YELLOW, width=0)
    d.line([(8, 8), (8, 34)], fill=YELLOW, width=3); d.line([(8, 8), (34, 8)], fill=YELLOW, width=3)
    d.line([(W - 8, H - 8), (W - 8, H - 34)], fill=YONDER, width=3); d.line([(W - 8, H - 8), (W - 34, H - 8)], fill=YONDER, width=3)
    out = WEB_DATA.parent / "og.png"
    img.save(out, optimize=True)
    print("wrote", out, out.stat().st_size // 1024, "kB")


if __name__ == "__main__":
    main()
