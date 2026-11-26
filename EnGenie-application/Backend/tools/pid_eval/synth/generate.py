"""Synthetic P&ID test drawings with exact truth.

Each drawing is built as a plant graph first and then drawn the way real P&IDs
look (instrument bubbles with the letters over the number, valve bow-ties,
equipment outlines, solid pipes, dashed signal lines, off-sheet flags, line
numbers, a title block), so every tag and every link is known exactly.

    python tools/pid_eval/synth/generate.py --level clean --count 5 --seed 1
    -> tools/pid_eval/synth/out/<name>.png + <name>.json  (truth for the scorers)

levels
    clean   CAD-like export
    dense   every optional loop and valve present
    scan    clean drawing degraded like a scan: slight skew, blur, noise, faded ink

The truth JSON is read by truth_manual.py / conn_truth.py, so the usual
live_any.py -> score_manual.py / score_live.py / score_review.py loop works on
these drawings unchanged. Rendered drawings are easier than real scans: keep
real hand-checked drawings in the evaluation as well.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent / "out"
W, H = 5100, 2920
PIPE, SIGNAL, THIN = 5, 3, 3


def _font(size: int):
    return ImageFont.load_default(size=size)


class Sheet:
    """Draws on a white sheet and records the truth of what it drew."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.img = Image.new("L", (W, H), 255)
        self.d = ImageDraw.Draw(self.img)
        self.f_tag, self.f_small, self.f_big = _font(30), _font(24), _font(40)
        self.equipment: dict[str, str] = {}
        self.instruments: list[str] = []
        self.required: set[tuple[str, str]] = set()
        self.flags: dict[str, tuple[float, float]] = {}
        self.line_labels: list[str] = []
        self.headers: list[str] = []

    # ── truth ──
    def link(self, a: str, b: str) -> None:
        self.required.add(tuple(sorted((a, b))))

    def chain(self, tags: list[str]) -> None:
        for a, b in zip(tags, tags[1:]):
            self.link(a, b)

    # ── lines ──
    def pipe(self, pts, arrow_at_end: bool = False) -> None:
        self.d.line(pts, fill=0, width=PIPE, joint="curve")
        if arrow_at_end:
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            ang = math.atan2(y1 - y0, x1 - x0)
            tip = (x1, y1)
            left = (x1 - 26 * math.cos(ang) + 11 * math.sin(ang), y1 - 26 * math.sin(ang) - 11 * math.cos(ang))
            right = (x1 - 26 * math.cos(ang) - 11 * math.sin(ang), y1 - 26 * math.sin(ang) + 11 * math.cos(ang))
            self.d.polygon([tip, left, right], fill=0)

    def thin(self, pts) -> None:
        self.d.line(pts, fill=0, width=THIN)

    def signal(self, pts, dash: int = 22, gap: int = 14) -> None:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            length = math.hypot(x1 - x0, y1 - y0)
            if length == 0:
                continue
            ux, uy = (x1 - x0) / length, (y1 - y0) / length
            pos = 0.0
            while pos < length:
                end = min(length, pos + dash)
                self.d.line([(x0 + ux * pos, y0 + uy * pos), (x0 + ux * end, y0 + uy * end)], fill=0, width=SIGNAL)
                pos = end + gap

    def text(self, x, y, s, font=None, anchor="mm") -> None:
        self.d.text((x, y), s, fill=0, font=font or self.f_small, anchor=anchor)

    # ── symbols ──
    def bubble(self, x, y, tag: str, panel: bool = False) -> None:
        letters, num = tag.split("-", 1)
        r = 54
        self.d.ellipse([x - r, y - r, x + r, y + r], fill=255, outline=0, width=THIN)
        if panel:                                    # shared display: a line through the bubble
            self.d.line([x - r, y, x + r, y], fill=0, width=2)
        self.text(x, y - 19, letters, self.f_tag)
        self.text(x, y + 21, num, self.f_tag)
        self.instruments.append(tag)

    def valve(self, x, y, tag: str, kind: str = "hand", label_dy: int = -58, vertical: bool = False) -> None:
        """A bow-tie on the line through (x, y); control valves get an actuator."""
        s = 24
        if vertical:
            pts1, pts2 = [(x - s, y - s), (x + s, y - s), (x, y)], [(x - s, y + s), (x + s, y + s), (x, y)]
        else:
            pts1, pts2 = [(x - s, y - s), (x - s, y + s), (x, y)], [(x + s, y - s), (x + s, y + s), (x, y)]
        fill = 0 if kind == "check_filled" else 255
        self.d.polygon(pts1, fill=255, outline=0)
        self.d.polygon(pts2, fill=fill, outline=0)
        self.d.line(pts1 + [pts1[0]], fill=0, width=THIN)
        self.d.line(pts2 + [pts2[0]], fill=0, width=THIN)
        if kind == "control":
            self.d.line([x, y - s, x, y - 64], fill=0, width=THIN)
            self.d.chord([x - 30, y - 94, x + 30, y - 34], 180, 360, fill=255, outline=0, width=THIN)
            self.d.line([x - 30, y - 64, x + 30, y - 64], fill=0, width=THIN)
            self.text(x + 34, y + 44, tag, self.f_small, anchor="lm")
        else:
            self.text(x, y + label_dy, tag, self.f_small)
        self.instruments.append(tag)

    def relief(self, x, y, tag: str) -> tuple[tuple[int, int], tuple[int, int]]:
        """Angle relief valve: inlet from below, outlet to the right. Returns (inlet, outlet)."""
        s = 24
        self.d.polygon([(x - s, y + s), (x + s, y + s), (x, y)], fill=255, outline=0)
        self.d.polygon([(x + s, y - s), (x + s, y + s), (x, y)], fill=255, outline=0)
        self.d.line([(x - s, y + s), (x + s, y + s), (x, y), (x - s, y + s)], fill=0, width=THIN)
        self.d.line([(x + s, y - s), (x + s, y + s), (x, y), (x + s, y - s)], fill=0, width=THIN)
        for i in range(4):                          # the spring
            self.d.line([x - 12, y - 12 - 10 * i, x + 12, y - 17 - 10 * i], fill=0, width=2)
        self.text(x - 40, y - 40, tag, self.f_small, anchor="rm")
        self.instruments.append(tag)
        return (x, y + s), (x + s, y)

    def orifice(self, x, y, tag: str) -> None:
        """An in-line flow element: two short bars across the pipe."""
        self.d.line([x - 8, y - 26, x - 8, y + 26], fill=0, width=4)
        self.d.line([x + 8, y - 26, x + 8, y + 26], fill=0, width=4)
        self.text(x, y + 52, tag, self.f_small)
        self.instruments.append(tag)

    def vessel(self, cx, top, bottom, tag: str, desc: str, kind: str = "vessel", wide: int = 220) -> None:
        x0, x1 = cx - wide // 2, cx + wide // 2
        self.d.rounded_rectangle([x0, top, x1, bottom], radius=wide // 2, fill=255, outline=0, width=PIPE)
        self.text(cx, bottom + 50, tag, self.f_big)
        self.text(cx, bottom + 92, desc, self.f_small)
        self.equipment[tag] = kind

    def pump(self, cx, cy, tag: str, desc: str) -> None:
        r = 55
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255, outline=0, width=PIPE)
        self.d.polygon([(cx - 20, cy - 30), (cx - 20, cy + 30), (cx + 34, cy)], outline=0)
        self.text(cx, cy + r + 45, tag, self.f_big)
        self.text(cx, cy + r + 85, desc, self.f_small)
        self.equipment[tag] = "other"

    def exchanger(self, cx, cy, tag: str, desc: str) -> None:
        r = 70
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255, outline=0, width=PIPE)
        zig = [(cx - r + 10, cy + 20)] + [(cx - r + 30 + 22 * i, cy - 25 if i % 2 == 0 else cy + 25) for i in range(5)] \
            + [(cx + r - 10, cy - 20)]
        self.d.line(zig, fill=0, width=THIN)
        self.text(cx, cy + r + 45, tag, self.f_big)
        self.text(cx, cy + r + 85, desc, self.f_small)
        self.equipment[tag] = "heat_exchanger"

    def flag(self, x0, y, name: str, printed: str, pointing: str = "right") -> tuple[int, int]:
        """Off-sheet connector; returns where the pipe meets it."""
        w, h = 300, 64
        if pointing == "right":
            pts = [(x0, y - h // 2), (x0 + w - 40, y - h // 2), (x0 + w, y), (x0 + w - 40, y + h // 2), (x0, y + h // 2)]
            attach = (x0 + w, y)
        else:
            pts = [(x0 + 40, y - h // 2), (x0 + w, y - h // 2), (x0 + w, y + h // 2), (x0 + 40, y + h // 2), (x0, y)]
            attach = (x0, y)
        self.d.polygon(pts, fill=255, outline=0)
        self.d.line(pts + [pts[0]], fill=0, width=THIN)
        self.text(x0 + w / 2, y, printed, self.f_small)
        self.flags[name] = (round((x0 + w / 2) / W * 1000, 1), round(y / W * 1000, 1))
        self.headers.append(printed)
        return attach

    def line_label(self, x, y, fluid: str, num: str, size: str) -> None:
        self.text(x, y, f'{size}"-{fluid}-{num}-A1A', self.f_small)
        self.line_labels.append(f"{fluid}-{num}")

    def title_block(self, title: str, number: str) -> None:
        x0, y0 = W - 1250, H - 330
        self.d.rectangle([x0, y0, W - 40, H - 40], outline=0, width=THIN)
        self.d.line([x0, y0 + 90, W - 40, y0 + 90], fill=0, width=2)
        self.text(x0 + 20, y0 + 45, title, self.f_big, anchor="lm")
        self.text(x0 + 20, y0 + 140, f"DRAWING No. {number}   REV. 0", self.f_small, anchor="lm")
        self.text(x0 + 20, y0 + 190, "NOTES: 1. ALL LINE SIZES IN INCHES.  2. SEE P&ID LEGEND SHEET.", self.f_small, anchor="lm")
        self.d.rectangle([40, 40, W - 40, H - 40], outline=0, width=THIN)       # the border


_DESCS = {"vessel": ["FEED DRUM", "SURGE DRUM", "KNOCK-OUT DRUM", "SEPARATOR"],
          "pump": ["FEED PUMP", "TRANSFER PUMP", "CHARGE PUMP"],
          "exchanger": ["FEED PREHEATER", "PRODUCT COOLER", "TRIM COOLER"]}
_FLUIDS = ["P", "PG", "HC", "CW", "N"]


def train(sh: Sheet, y: int, area: int, names: dict, full: bool) -> None:
    """One process train along the line at height y (upper part y-620 .. lower y+330)."""
    rng = sh.rng
    n = lambda k: f"{area}{k:02d}"                   # tag numbers: 1301, 1302 ... for area 13
    y2 = y + 140                                     # the outlet line below the vessel nozzle
    fluid = rng.choice(_FLUIDS)

    # feed: flag -> hand valve -> [flow loop] -> vessel
    a = sh.flag(60, y, names["in"], names["in_printed"], "right")
    hv = f"HV-{n(1)}"
    run = [names["in"], hv]
    flow = full or rng.random() < 0.75
    sh.pipe([a, (1340, y)], arrow_at_end=True)
    sh.valve(560, y, hv)
    sh.line_label(1150, y - 34, fluid, n(1), rng.choice(["2", "3", "4", "6"]))
    if flow:
        fe, ft, fic, fv = f"FE-{n(2)}", f"FT-{n(2)}", f"FIC-{n(2)}", f"FV-{n(2)}"
        sh.orifice(760, y, fe)
        sh.thin([(760, y - 26), (760, y - 116)])
        sh.bubble(760, y - 170, ft)
        sh.signal([(760, y - 224), (760, y - 316)])
        sh.bubble(760, y - 370, fic, panel=True)
        sh.valve(1000, y, fv, kind="control")
        sh.signal([(814, y - 370), (1000, y - 370), (1000, y - 94)])
        run += [fe, fv]
        sh.link(fe, ft); sh.link(ft, fic); sh.link(fic, fv)
    vessel = f"V-{n(10)}"
    run.append(vessel)
    sh.chain(run)
    sh.vessel(1450, y - 300, y + 200, vessel, rng.choice(_DESCS["vessel"]))

    # level loop on the vessel
    lt, lic, lv = f"LT-{n(11)}", f"LIC-{n(11)}", f"LV-{n(11)}"
    sh.thin([(1560, y - 150), (1626, y - 150)])
    sh.bubble(1680, y - 150, lt)
    sh.signal([(1680, y - 204), (1680, y - 316)])
    sh.bubble(1680, y - 370, lic, panel=True)
    sh.link(vessel, lt); sh.link(lt, lic)

    # relief to the header
    if full or rng.random() < 0.8:
        psv = f"PSV-{n(14)}"
        sh.pipe([(1450, y - 300), (1450, y - 520)])
        inlet, outlet = sh.relief(1450, y - 544, psv)
        hdr = sh.flag(W - 360, y - 544, names["relief"], names["relief_printed"], "right")
        sh.pipe([outlet, (W - 360, y - 544)], arrow_at_end=True)
        del hdr
        sh.link(vessel, psv); sh.link(psv, names["relief"])

    # outlet: vessel -> pump -> gauge tap -> level valve -> exchanger -> [temperature] -> check -> flag
    pump = f"P-{n(12)}"
    sh.pipe([(1560, y2), (1795, y2)])
    sh.pump(1850, y2, pump, rng.choice(_DESCS["pump"]))
    sh.pipe([(1905, y2), (2430, y2)], arrow_at_end=True)
    out = [vessel, pump]
    if full or rng.random() < 0.85:
        pi = f"PI-{n(13)}"
        sh.thin([(2010, y2), (2010, y2 + 116)])
        sh.bubble(2010, y2 + 170, pi)
        out.append(pi)
    sh.valve(2200, y2, lv, kind="control")
    sh.signal([(1734, y - 370), (2200, y - 370), (2200, y2 - 94)])
    sh.link(lic, lv)
    out.append(lv)
    hx = f"E-{n(20)}"
    out.append(hx)
    sh.exchanger(2500, y2, hx, rng.choice(_DESCS["exchanger"]))
    sh.pipe([(2570, y2), (3600, y2)])
    sh.line_label(3000, y2 - 34, fluid, n(2), rng.choice(["2", "3", "4"]))
    if full or rng.random() < 0.75:
        te, ti = f"TE-{n(21)}", f"TI-{n(21)}"
        sh.thin([(2800, y2), (2800, y2 - 116)])
        sh.bubble(2800, y2 - 170, te)
        sh.signal([(2854, y2 - 170), (2946, y2 - 170)])
        sh.bubble(3000, y2 - 170, ti, panel=True)
        out.append(te)
        sh.link(te, ti)
    if full or rng.random() < 0.8:
        ck = f"CK-{n(40)}"
        sh.valve(3900, y2, ck, kind="check_filled")
        out.append(ck)
    hv2 = f"HV-{n(41)}"
    sh.valve(4250, y2, hv2)
    out.append(hv2)
    sh.pipe([(3600, y2), (W - 400, y2)], arrow_at_end=True)
    sh.flag(W - 400, y2, names["out"], names["out_printed"], "right")
    out.append(names["out"])
    sh.chain(out)


_IN = [("FEED", "FROM TANK FARM"), ("CRUDE", "CRUDE FROM T-01"), ("WATER-IN", "RAW WATER IN")]
_OUT = [("PRODUCT", "TO STORAGE"), ("TO-REACTOR", "TO REACTOR R-501"), ("RUNDOWN", "TO RUNDOWN")]
_RELIEF = [("RELIEF-A", "TO FLARE HEADER"), ("RELIEF-B", "TO VENT HEADER")]


def scanify(img: Image.Image, rng: random.Random) -> Image.Image:
    """Degrade like a scan: slight skew, blur, faded ink, speckle (test images only)."""
    import numpy as np
    img = img.rotate(rng.uniform(-0.8, 0.8), resample=Image.Resampling.BICUBIC, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.2)))
    a = np.asarray(img).astype(np.float32)
    a = 55 + a * (200 / 255)                                     # ink no darker than ~55, paper ~255
    a += np.random.default_rng(rng.randrange(1 << 30)).normal(0, 9, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def generate(seed: int, level: str = "clean") -> tuple[Image.Image, dict]:
    rng = random.Random(seed * 7919 + {"clean": 0, "dense": 1, "scan": 2}[level])
    sh = Sheet(rng)
    areas = rng.sample(range(11, 59), 2)
    ins, outs = rng.sample(_IN, 2), rng.sample(_OUT, 2)
    full = level == "dense"
    for i, (y, area) in enumerate(((900, areas[0]), (2050, areas[1]))):
        names = {"in": f"{ins[i][0]}-{i + 1}", "in_printed": ins[i][1],
                 "out": f"{outs[i][0]}-{i + 1}", "out_printed": outs[i][1],
                 "relief": _RELIEF[i][0], "relief_printed": _RELIEF[i][1]}
        train(sh, y, area, names, full)
    number = f"SYN-{level[0].upper()}{seed:03d}"
    sh.title_block(f"SYNTHETIC PROCESS UNIT {areas[0]}/{areas[1]}", number)
    img = scanify(sh.img, rng) if level == "scan" else sh.img
    name = f"syn{level[0]}{seed:03d}"
    truth = {
        "name": name, "level": level, "seed": seed,
        "tags": {"equipment": sh.equipment, "instruments": sorted(set(sh.instruments)), "inferred": [],
                 "not_symbols": [], "line_labels": sorted(set(sh.line_labels)), "headers": sh.headers},
        "connections": {"flags": sh.flags, "required": sorted(list(p) for p in sh.required), "optional": []},
    }
    return img, truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", choices=["clean", "dense", "scan"], default="clean")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for s in range(args.seed, args.seed + args.count):
        img, truth = generate(s, args.level)
        img.save(OUT / f"{truth['name']}.png")
        (OUT / f"{truth['name']}.json").write_text(json.dumps(truth, indent=1))
        print(f"{truth['name']}: {len(truth['tags']['equipment'])} equipment, "
              f"{len(truth['tags']['instruments'])} instruments, {len(truth['connections']['required'])} links")


if __name__ == "__main__":
    main()
