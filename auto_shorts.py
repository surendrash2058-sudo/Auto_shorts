"""
auto_shorts.py - makes ONE "What if" YouTube Short from the next unfinished topic
in topics.json, then (optionally) uploads it.

Steps: find trends -> Gemini writes script -> stock video -> voice (edge-tts, free) -> word-synced captions -> render frame by frame -> upload

Run:
    python auto_shorts.py            # make the next video only
    python auto_shorts.py --upload   # make it and upload to YouTube
    python auto_shorts.py --list     # show the topic queue
    python auto_shorts.py --auto     # FULL AUTO: trending idea -> script -> video -> upload
                                     # (this is what the daily GitHub Action runs)
"""
import argparse
import asyncio
import json
import os
import random
import re
import time
import html
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = Path(__file__).parent
TOPICS = HERE / "topics.json"
OUT = HERE / "output"
IMAGES = HERE / "images"          # optional: put your own pictures here
W, H, FPS = 1080, 1920, 30
VOICE = "en-US-AndrewNeural"      # natural-sounding male English voice

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

PALETTES = [((20, 24, 60), (90, 40, 140)), ((10, 50, 70), (20, 120, 120)),
            ((60, 20, 30), (160, 60, 60)), ((20, 40, 20), (70, 130, 60))]


def get_font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ---------- 1. voice + word timings ----------
async def make_voice(text, mp3_path):
    """Generate speech with retries and alternate Microsoft Edge voices."""
    import edge_tts

    voices = [VOICE, "en-GB-RyanNeural", "en-US-GuyNeural"]
    last_error = None
    for attempt, voice in enumerate(voices, start=1):
        words = []
        try:
            try:
                comm = edge_tts.Communicate(text, voice, rate="-5%", pitch="-1Hz", volume="+0%", boundary="WordBoundary")
            except TypeError:                  # older edge-tts versions
                comm = edge_tts.Communicate(text, voice)
            with open(mp3_path, "wb") as audio_file:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        words.append((chunk["text"], chunk["offset"] / 1e7,
                                      chunk["duration"] / 1e7))
            if mp3_path.stat().st_size > 1000 and words:
                print(f"Voice generated successfully with {voice}.")
                return words
            raise RuntimeError("Edge TTS returned no usable audio or word timings.")
        except Exception as exc:
            last_error = exc
            if mp3_path.exists():
                mp3_path.unlink()
            print(f"Voice attempt {attempt}/{len(voices)} failed ({voice}): {exc}")
            if attempt < len(voices):
                await asyncio.sleep(3 * attempt)

    raise RuntimeError(
        "Voice generation failed with all fallback voices. "
        f"Last Edge TTS error: {last_error}"
    )


# ---------- 2. backgrounds ----------
def gradient(c1, c2):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return img


def cover(path, dark=0.55):
    img = Image.open(path).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    x, y = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((x, y, x + W, y + H))
    return Image.eval(img, lambda v: int(v * dark))   # darken so captions are readable


def load_backgrounds():
    files = sorted(p for p in IMAGES.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")) \
        if IMAGES.exists() else []
    if files:
        return [cover(p) for p in files]
    return [gradient(*p) for p in PALETTES]


# ---------- 3. render ----------
def group_words(words, n=3):
    return [list(range(i, min(i + n, len(words)))) for i in range(0, len(words), n)]


def draw_frame(bg, title, words, groups, idx):
    img = bg.copy() if bg is not None else Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Keep the title inside the Shorts safe area and wrap long titles.
    tf = get_font(42)
    title_words = title.split()
    title_lines, line = [], ""
    for word in title_words:
        candidate = (line + " " + word).strip()
        if d.textlength(candidate, font=tf) > W * 0.84 and line:
            title_lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        title_lines.append(line)
    title_lines = title_lines[:2]
    for n, title_line in enumerate(title_lines):
        d.text((W // 2, 125 + n * 52), title_line, font=tf,
               fill=(255, 255, 255), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
    if idx is not None:
        grp = next(g for g in groups if idx in g)
        parts = [words[i][0] for i in grp]
        size = 84
        while True:
            cf = get_font(size)
            sizes = [d.textlength(p + " ", font=cf) for p in parts]
            if sum(sizes) <= W * 0.84 or size <= 42:
                break
            size -= 4
        x = (W - sum(sizes)) / 2
        for i, p, sz in zip(grp, parts, sizes):
            col = (255, 220, 40) if i == idx else (255, 255, 255)
            d.text((x + 3, H * 0.59 + 3), p, font=cf, fill=(0, 0, 0), anchor="lm")
            d.text((x, H * 0.59), p, font=cf, fill=col, anchor="lm",
                   stroke_width=1, stroke_fill=(0, 0, 0))
            x += sz
    return img


# ---------- 3b. built-in animations (free: no internet, no keys) ----------
import math

GW, GH = 720, 1280                       # animation grid; upscaled to W x H
_cache = {}


def rv(key, n):
    """n fixed random tuples per key (same every frame)."""
    if key not in _cache:
        r = random.Random(hash(key) & 0xFFFF)
        _cache[key] = [(r.random(), r.random(), r.random(), r.random()) for _ in range(n)]
    return _cache[key]


def grad_bg(top, bot):
    key = ("bg", top, bot)
    if key not in _cache:
        im = Image.new("RGB", (GW, GH))
        d = ImageDraw.Draw(im)
        for y in range(GH):
            t = y / GH
            d.line([(0, y), (GW, y)], fill=tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(3)))
        _cache[key] = im
    return _cache[key].copy()


def glow_sprite(r, col):
    key = ("g", int(r), col)
    if key not in _cache:
        sz = int(r * 4)
        layer = Image.new("RGBA", (sz, sz), col + (0,))
        ImageDraw.Draw(layer).ellipse([sz / 2 - r * 1.2, sz / 2 - r * 1.2, sz / 2 + r * 1.2, sz / 2 + r * 1.2],
                                      fill=col + (150,))
        _cache[key] = layer.filter(ImageFilter.GaussianBlur(r * 0.5))
    return _cache[key]


def sphere_sprite(r, base):
    key = ("s", r, base)
    if key not in _cache:
        sz = 2 * r
        im = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        steps = max(12, r // 3)
        for i in range(steps):
            f = i / (steps - 1)
            rr = r * (1 - f * 0.8)
            cx, cy = r - r * 0.2 * f, r - r * 0.2 * f
            col = tuple(min(255, int(base[k] * (0.45 + 0.75 * f))) for k in range(3))
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col + (255,))
        _cache[key] = im
    return _cache[key]


def circle_mask(sz):
    key = ("m", sz)
    if key not in _cache:
        m = Image.new("L", (sz, sz), 0)
        ImageDraw.Draw(m).ellipse([0, 0, sz - 1, sz - 1], fill=255)
        _cache[key] = m
    return _cache[key]


def put(cv, sp, x, y, a=1.0):
    m = sp.getchannel("A") if sp.mode == "RGBA" else circle_mask(sp.width)
    if a < 1:
        m = m.point(lambda v: int(v * max(a, 0)))
    cv.paste(sp.convert("RGB"), (int(x - sp.width / 2), int(y - sp.height / 2)), m)


def glow(cv, x, y, r, col, a=1.0):
    put(cv, glow_sprite(r, col), x, y, a)


def starfield(cv, d, t, key, n=60):
    for i, (a, b, c, e) in enumerate(rv(("st", key), n)):
        y = (b * GH - 10 * t * (0.4 + c)) % GH
        v = int(130 + 120 * math.sin(t * 2 + i))
        r = 1 + int(e * 2)
        d.ellipse([a * GW - r, y - r, a * GW + r, y + r], fill=(v, v, min(255, v + 20)))


def has(txt, pat):
    return re.search(pat, txt) is not None


def stick(d, x, y, s, col=(255, 255, 255), pose=0.0):
    """Stick figure; (x, y) = feet. s = height."""
    hr = s * 0.13
    d.ellipse([x - hr, y - s + 0, x + hr, y - s + 2 * hr], fill=col)
    d.line([(x, y - s + 2 * hr), (x, y - s * 0.38)], fill=col, width=max(2, int(s * 0.07)))
    d.line([(x, y - s * 0.38), (x - s * 0.18, y)], fill=col, width=max(2, int(s * 0.07)))
    d.line([(x, y - s * 0.38), (x + s * 0.18, y)], fill=col, width=max(2, int(s * 0.07)))
    up = s * 0.2 * pose
    d.line([(x, y - s * 0.7), (x - s * 0.25, y - s * 0.5 - up)], fill=col, width=max(2, int(s * 0.06)))
    d.line([(x, y - s * 0.7), (x + s * 0.25, y - s * 0.5 - up)], fill=col, width=max(2, int(s * 0.06)))


def anim_cosmos(cv, d, t, p, txt, i):
    starfield(cv, d, t, "cos")
    glow(cv, 360, 430, 150 + 12 * math.sin(t * 3), (120, 90, 255))
    put(cv, sphere_sprite(110, (150, 120, 255)), 360, 430)
    for k in range(3):
        rr = 150 + ((t * 60 + k * 70) % 210)
        d.ellipse([360 - rr, 430 - rr, 360 + rr, 430 + rr], outline=(160, 140, 255), width=3)
    for a, b, c, e in rv(("cp", i), 14):
        ang = t * (0.5 + c) + a * 6.28
        rr = 200 + 150 * b
        x, y = 360 + rr * math.cos(ang), 430 + rr * 0.7 * math.sin(ang)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(255, 230, 150))


def anim_sun(cv, d, t, p, txt, i):
    starfield(cv, d, t, "sun", 40)
    vanish = has(txt, r"vanish|disappear|gone")
    a = max(0.0, 1 - p * 1.3) if vanish else 1.0
    glow(cv, 360, 430, 190 + 12 * math.sin(t * 3), (255, 160, 30), a)
    if a > 0.05:
        for k in range(14):
            ang = t * 0.4 + k * math.pi / 7
            x1, y1 = 360 + 175 * math.cos(ang), 430 + 175 * math.sin(ang)
            x2, y2 = 360 + (230 + 20 * math.sin(t * 4 + k)) * math.cos(ang), 430 + (230 + 20 * math.sin(t * 4 + k)) * math.sin(ang)
            d.line([(x1, y1), (x2, y2)], fill=(255, int(190 * a + 30), 60), width=7)
    put(cv, sphere_sprite(150, (255, 190, 40)), 360, 430, a)
    ex, ey = 360 + 290 * math.cos(t * 0.8), 430 + 120 * math.sin(t * 0.8) + 300
    if vanish and p > 0.5:
        k = (p - 0.5) * 2
        ex, ey = ex + k * 500, ey - k * 250
    put(cv, sphere_sprite(34, (40, 120, 230)), ex, ey)


def anim_earth(cv, d, t, p, txt, i):
    starfield(cv, d, t, "earth", 50)
    r = 210
    stopped = has(txt, r"stop|halt|standing still")
    speed = 0 if stopped else 55
    glow(cv, 360, 450, r * 0.95, (70, 150, 255))
    tmp = sphere_sprite(r, (35, 95, 200)).convert("RGB")
    td = ImageDraw.Draw(tmp)
    for a, b, c, e in rv(("cont", 0), 7):
        for off in (0, -4 * r):
            x = (a * 4 * r - speed * t) % (4 * r) + off
            td.ellipse([x - 40 - c * 50, b * 2 * r - 25 - e * 40, x + 40 + c * 50, b * 2 * r + 25 + e * 40], fill=(60, 160, 80))
    cv.paste(tmp, (360 - r, 450 - r), circle_mask(2 * r))
    if stopped:
        for a, b, c, e in rv(("wind", i), 16):
            x = (a * GW + 500 * t * (0.6 + c)) % GW
            y = 150 + b * 600
            d.line([(x, y), (x + 50 + 40 * e, y)], fill=(220, 235, 255), width=3)


def anim_moon(cv, d, t, p, txt, i):
    starfield(cv, d, t, "moon", 60)
    vanish = has(txt, r"vanish|disappear|gone")
    a = max(0.0, 1 - p * 1.3) if vanish else 1.0
    if "moon_sp" not in _cache:
        sp = sphere_sprite(150, (205, 205, 210)).copy()
        sd = ImageDraw.Draw(sp)
        for cx, cy, rr in [(110, 120, 34), (190, 90, 22), (180, 190, 40), (95, 205, 20), (230, 150, 16)]:
            sd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(150, 150, 158, 255))
        sp.putalpha(circle_mask(300))
        _cache["moon_sp"] = sp
    glow(cv, 360, 380, 190, (200, 210, 255), a * 0.7)
    put(cv, _cache["moon_sp"], 360, 380, a)
    amp = (55 + 35 * math.sin(t * 1.2)) * (1 - p if vanish else 1)
    pts = [(x, 900 + amp * math.sin(x / 70 + t * 2)) for x in range(0, GW + 20, 20)]
    d.polygon(pts + [(GW, GH), (0, GH)], fill=(25, 80, 160))
    pts2 = [(x, 940 + amp * 0.7 * math.sin(x / 55 - t * 1.6)) for x in range(0, GW + 20, 20)]
    d.polygon(pts2 + [(GW, GH), (0, GH)], fill=(15, 50, 120))


def anim_black_hole(cv, d, t, p, txt, i):
    starfield(cv, d, t, "bh", 50)
    glow(cv, 360, 430, 230, (255, 120, 20), 0.8)
    for k in range(14):
        rr = 115 + k * 10
        v = 0.55 + 0.45 * math.sin(t * 3 + k * 0.7)
        col = (int(255 * v), int((120 + k * 8) * v), int(40 * v))
        d.ellipse([360 - rr * 1.7, 430 - rr * 0.42, 360 + rr * 1.7, 430 + rr * 0.42], outline=col, width=4)
    d.ellipse([360 - 98, 430 - 98, 360 + 98, 430 + 98], fill=(0, 0, 0), outline=(255, 210, 150), width=3)
    ox, oy = 600 - 240 * p, 250 + 180 * p
    w, h = 22 * (1 - 0.55 * p), 22 + 170 * p
    d.ellipse([ox - w, oy - h / 2, ox + w, oy + h / 2], fill=(235, 245, 255))


def anim_ocean(cv, d, t, p, txt, i):
    deep = has(txt, r"trench|deep|pressure|dive|mile|bottom")
    if deep:
        for a, b, c, e in rv(("bub", i), 26):
            y = (b * GH - 90 * t * (0.5 + c)) % GH
            x = a * GW + 10 * math.sin(t * 2 + e * 6)
            d.ellipse([x - 4 - 6 * e, y - 4 - 6 * e, x + 4 + 6 * e, y + 4 + 6 * e], outline=(150, 200, 255), width=2)
        sx, sy = 360 + 40 * math.sin(t), 230 + 560 * p
        d.ellipse([sx - 100, sy - 40, sx + 100, sy + 40], fill=(255, 200, 30))
        d.ellipse([sx - 20, sy - 30, sx + 30, sy + 10], fill=(150, 220, 255))
        d.rectangle([sx - 6, sy - 62, sx + 6, sy - 38], fill=(255, 200, 30))
        glow(cv, sx, sy + 40, 120, (255, 240, 150), 0.5)
    else:
        glow(cv, 580, 250, 110, (255, 230, 150), 0.8)
        d.ellipse([540, 210, 620, 290], fill=(255, 235, 160))
    for k, (base, col) in enumerate([(640, (60, 150, 220)), (730, (35, 105, 190)), (830, (20, 70, 150))]):
        amp = 28 + k * 6
        pts = [(x, base + amp * math.sin(x / (60 + 20 * k) + t * (1.5 + k * 0.5) + k)) for x in range(0, GW + 20, 20)]
        d.polygon(pts + [(GW, GH), (0, GH)], fill=col)


def anim_ice(cv, d, t, p, txt, i):
    glow(cv, 360, 430, 220, (170, 230, 255), 0.7)
    cx, cy = 360, 430
    rot = t * 0.25
    for k in range(6):
        ang = rot + k * math.pi / 3
        ex, ey = cx + 190 * math.cos(ang), cy + 190 * math.sin(ang)
        d.line([(cx, cy), (ex, ey)], fill=(235, 250, 255), width=8)
        for f in (0.45, 0.7):
            bx, by = cx + 190 * f * math.cos(ang), cy + 190 * f * math.sin(ang)
            for s in (-1, 1):
                a2 = ang + s * 0.8
                d.line([(bx, by), (bx + 60 * math.cos(a2), by + 60 * math.sin(a2))], fill=(235, 250, 255), width=6)
    for a, b, c, e in rv(("snow", i), 70):
        y = (b * GH + (60 + 90 * c) * t) % GH
        x = a * GW + 22 * math.sin(t * 1.5 + e * 6)
        r = 2 + 4 * e
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
    d.rectangle([0, 1020, GW, GH], fill=(225, 240, 252))


def anim_fire(cv, d, t, p, txt, i):
    glow(cv, 360, 950, 330, (255, 110, 20), 0.9)
    for k in range(10):
        x = 40 + k * 70
        h = 260 + 110 * math.sin(t * 5 + k * 1.7) + 70 * math.sin(t * 9 + k)
        d.polygon([(x - 55, 1020), (x + 8 * math.sin(t * 6 + k), 1020 - h), (x + 55, 1020)], fill=(235, 80, 15))
        h2 = h * 0.62
        d.polygon([(x - 32, 1020), (x + 5 * math.sin(t * 7 + k), 1020 - h2), (x + 32, 1020)], fill=(255, 190, 40))
    for a, b, c, e in rv(("ember", i), 30):
        y = 1000 - ((t * (80 + 120 * c) + b * 900) % 900)
        x = a * GW + 25 * math.sin(t * 2 + e * 6)
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 210, 90))


def anim_network(cv, d, t, p, txt, i):
    starfield(cv, d, t, "net", 20)
    dead = has(txt, r"stop|offline|down|fail|dead|without|cut|lose|lost")
    k = min(1.0, p * 1.4) if dead else 0.0
    nodes = [(110 + a * 500, 190 + b * 720) for a, b, c, e in rv(("node", 0), 15)]
    edges = [(a, b) for a in range(15) for b in range(a + 1, 15)
             if (nodes[a][0] - nodes[b][0]) ** 2 + (nodes[a][1] - nodes[b][1]) ** 2 < 270 ** 2]
    live, deadc = (70, 170, 230), (150, 60, 60)
    col = tuple(int(live[c] + (deadc[c] - live[c]) * k) for c in range(3))
    for n, (a, b) in enumerate(edges):
        d.line([nodes[a], nodes[b]], fill=tuple(int(v * 0.55) for v in col), width=3)
        if k < 0.6:
            f = (t * 0.6 + n * 0.37) % 1
            x = nodes[a][0] + (nodes[b][0] - nodes[a][0]) * f
            y = nodes[a][1] + (nodes[b][1] - nodes[a][1]) * f
            d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 255, 255))
    for n, (x, y) in enumerate(nodes):
        glow(cv, x, y, 26 + 5 * math.sin(t * 3 + n), col, 1 - 0.6 * k)
        d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=col)


def anim_brain(cv, d, t, p, txt, i):
    starfield(cv, d, t, "brain", 40)
    if has(txt, r"brain|memory|focus|mind|halluc|thought|see things"):
        for dx in (-85, 85):
            glow(cv, 360 + dx, 430, 150, (255, 120, 190), 0.6)
            d.ellipse([360 + dx - 150, 430 - 150, 360 + dx + 150, 430 + 150], fill=(245, 150, 190), outline=(200, 90, 140), width=5)
        for k in range(8):
            y = 330 + k * 28
            d.arc([250 + (k % 3) * 40, y - 40, 400 + (k % 3) * 40, y + 40], 0, 180, fill=(200, 90, 140), width=4)
        for a, b, c, e in rv(("syn", i), 12):
            x, y = 220 + a * 280, 320 + b * 220
            r = 6 + 6 * abs(math.sin(t * 3 + e * 6))
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 245, 160))
    else:
        glow(cv, 330, 400, 200, (255, 235, 170), 0.6)
        d.ellipse([330 - 140, 400 - 140, 330 + 140, 400 + 140], fill=(255, 240, 180))
        bgc = cv.getpixel((420, 360))
        d.ellipse([330 - 140 + 85, 400 - 140 - 25, 330 + 140 + 85, 400 + 140 - 25], fill=bgc)
    for k in range(3):
        f = ((t * 0.5 + k / 3) % 1)
        d.text((500 + 40 * math.sin(f * 6 + k), 700 - f * 380), "Z", font=get_font(int(36 + 60 * f)),
               fill=(220, 230, 255), anchor="mm")


def anim_gravity(cv, d, t, p, txt, i):
    heavy = has(txt, r"doubl|twice|heavy|weigh|collaps")
    floating = has(txt, r"float|zero|switch|without gravity|no gravity")
    d.rectangle([0, 930, GW, GH], fill=(55, 125, 65))
    h = 70 if heavy else 210
    jump = abs(math.sin(t * 3.2)) * h
    if floating:
        stick(d, 360 + 40 * math.sin(t), 880 - p * 520, 230, pose=1.0)
    else:
        stick(d, 360, 930 - jump, 230, pose=0.0 if heavy else 1.0)
        d.ellipse([360 - 60 - jump * 0.2, 925, 360 + 60 + jump * 0.2, 940], fill=(35, 90, 45))
    d.polygon([(590, 330), (640, 330), (640, 470), (680, 470), (615, 560), (550, 470), (590, 470)], fill=(255, 200, 60))
    d.text((615, 620), "2x" if heavy else "g", font=get_font(70), fill=(255, 255, 255), anchor="mm")


def anim_crowd(cv, d, t, p, txt, i):
    starfield(cv, d, t, "crowd", 40)
    glow(cv, 360, 1400, 600, (70, 140, 220), 0.5)
    d.ellipse([360 - 800, 1500 - 800, 360 + 800, 1500 + 800], fill=(35, 100, 175))
    vanish = has(txt, r"vanish|disappear|gone")
    a = max(0.0, 1 - p * 1.3) if vanish else 1.0
    jump = has(txt, r"jump")
    col = tuple(int(255 * a + 35 * (1 - a)) for _ in range(3))
    for k in range(45):
        ang = math.radians(-70 + k * 140 / 44) - math.pi / 2
        bx, by = 360 + 800 * math.cos(ang), 1500 + 800 * math.sin(ang)
        hop = 26 * abs(math.sin(t * 3.2)) if jump else 6 * abs(math.sin(t * 2 + k))
        nx, ny = math.cos(ang), math.sin(ang)
        stick(d, bx + nx * hop, by + ny * hop, 62, col, pose=1.0 if jump else 0.0)


def anim_clock(cv, d, t, p, txt, i):
    starfield(cv, d, t, "clock", 40)
    glow(cv, 360, 440, 260, (255, 230, 150), 0.5)
    d.ellipse([130, 210, 590, 670], fill=(248, 248, 252), outline=(60, 60, 90), width=10)
    for k in range(12):
        a = k * math.pi / 6
        d.line([(360 + 195 * math.sin(a), 440 - 195 * math.cos(a)), (360 + 215 * math.sin(a), 440 - 215 * math.cos(a))],
               fill=(40, 40, 70), width=8)
    for ln, spd, w, col in [(120, 0.21, 12, (30, 30, 60)), (175, 2.5, 8, (30, 30, 60)), (190, 6.0, 4, (220, 40, 40))]:
        a = t * spd
        d.line([(360, 440), (360 + ln * math.sin(a), 440 - ln * math.cos(a))], fill=col, width=w)
    d.ellipse([348, 428, 372, 452], fill=(30, 30, 60))


def anim_city(cv, d, t, p, txt, i):
    starfield(cv, d, t, "city", 70)
    blackout = has(txt, r"dark|out|fail|stop|blackout|grid|vanish|disappear|gone")
    glow(cv, 580, 260, 90, (255, 245, 200), 0.6)
    d.ellipse([545, 225, 615, 295], fill=(255, 248, 215))
    x = 10
    for n, (a, b, c, e) in enumerate(rv(("bld", 0), 8)):
        w, h = 70 + a * 40, 220 + b * 360
        d.rectangle([x, 1000 - h, x + w, 1000], fill=(18, 20, 45))
        for wy in range(int(1000 - h + 20), 980, 34):
            for wx in range(int(x + 10), int(x + w - 14), 24):
                r = rv(("win", n * 100 + wy), 8)[(wx // 24) % 8][0]
                lit = r < (max(0.0, 0.8 - p * 1.0) if blackout else 0.8 + 0.1 * math.sin(t + wy))
                d.rectangle([wx, wy, wx + 12, wy + 18], fill=(255, 215, 110) if lit else (30, 32, 60))
        x += w + 8


ANIMS = {"cosmos": anim_cosmos, "sun": anim_sun, "earth": anim_earth, "moon": anim_moon,
         "black_hole": anim_black_hole, "ocean": anim_ocean, "ice": anim_ice, "fire": anim_fire,
         "network": anim_network, "brain": anim_brain, "gravity": anim_gravity, "crowd": anim_crowd,
         "clock": anim_clock, "city": anim_city}

ANIM_BG = {"cosmos": ((8, 6, 30), (40, 20, 80)), "sun": ((5, 8, 25), (35, 12, 55)), "earth": ((4, 6, 24), (14, 20, 60)),
           "moon": ((6, 8, 30), (14, 24, 70)), "black_hole": ((2, 2, 10), (24, 8, 40)), "ocean": ((120, 190, 235), (25, 70, 140)),
           "ice": ((190, 230, 252), (90, 150, 215)), "fire": ((25, 0, 0), (110, 30, 0)), "network": ((5, 14, 36), (10, 44, 78)),
           "brain": ((10, 8, 40), (34, 12, 66)), "gravity": ((25, 35, 80), (90, 140, 200)), "crowd": ((10, 6, 36), (50, 20, 90)),
           "clock": ((12, 16, 46), (44, 30, 96)), "city": ((8, 8, 36), (50, 34, 84))}
ANIM_BG["ocean"] = ((120, 190, 235), (25, 70, 140))

ANIM_RULES = [
    ("black_hole", r"black hole|spaghett|event horizon"),
    ("crowd", r"everyone|people|human|crowd|billion"),
    ("network", r"internet|network|wifi|online|bank|data\b|phone"),
    ("brain", r"sleep|slept|awake|brain|dream|memory|focus|halluc"),
    ("ice", r"freez|frozen|\bice\b|snow|cold"),
    ("fire", r"\bfire\b|burn|\bhot\b|heat|melt|explo|vapor"),
    ("ocean", r"ocean|\bsea\b|wave|water|tsunami|trench|pressure|flood"),
    ("sun", r"\bsun\b|solar|sunlight"),
    ("gravity", r"weigh|jump|float|heavy|doubl"),
    ("moon", r"moon|tide|lunar"),
    ("earth", r"earth|planet|spin|orbit|equator|wind|plant|nature|tree|animal"),
    ("gravity", r"gravit"),
    ("city", r"power|grid|lights|city|building|electric|dark|night"),
    ("clock", r"clock|minute|hour|second|time\b|\bday|week|year"),
]


def pick_anim(scene_text, title=""):
    for text in (scene_text.lower(), title.lower()):
        for name, pat in ANIM_RULES:
            if re.search(pat, text):
                return name
    return "cosmos"


def anim_frame(name, t, p, txt, i):
    if name.startswith("3d:"):
        return render3d(name[3:], t, p, txt.lower(), i)
    top, bot = ANIM_BG[name]
    cv = grad_bg(top, bot)
    d = ImageDraw.Draw(cv)
    ANIMS[name](cv, d, t, min(max(p, 0.0), 1.0), txt.lower(), i)
    return cv.resize((W, H), Image.BICUBIC)


# ---------- 3c. 3D renderer (numpy, no GPU): lit spheres, planets, black hole ----------
RW, RH = 540, 960                        # 3D render size; upscaled to W x H
_T3 = {}


def fbm(h, w, octaves, seed, base=(4, 8), periodic=True):
    """Fractal noise 0..1 (wraps left-right when periodic)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp = 1.0
    for o in range(octaves):
        gh, gw = base[0] * 2 ** o, base[1] * 2 ** o
        g = rng.random((gh, gw + 1)).astype(np.float32)
        if periodic:
            g[:, -1] = g[:, 0]
        out += np.asarray(Image.fromarray(g).resize((w, h), Image.BICUBIC), dtype=np.float32) * amp
        amp *= 0.5
    out -= out.min()
    return out / max(float(out.max()), 1e-6)


def lerp_ramp(n, stops):
    """Colour ramp: n (any shape, 0..1) -> (..., 3). stops = [(pos, (r,g,b)), ...]"""
    import numpy as np
    pos = [s[0] for s in stops]
    return np.stack([np.interp(n, pos, [s[1][c] for s in stops]) for c in range(3)], axis=-1).astype(np.float32)


def earth_tex():
    if "earth" in _T3:
        return _T3["earth"]
    import numpy as np
    TH, TW = 512, 1024
    h = fbm(TH, TW, 6, 11)
    sea = 0.55
    lat = np.repeat(((0.5 - np.arange(TH) / TH) * np.pi)[:, None], TW, 1)
    land = h > sea
    d = np.clip((sea - h) * 5, 0, 1)[..., None]
    ocean = np.array([0.10, 0.34, 0.60], np.float32) * (1 - d) + np.array([0.01, 0.06, 0.22], np.float32) * d
    e = np.clip((h - sea) * 6, 0, 1)[..., None]
    m = fbm(TH, TW, 5, 23)[..., None]
    grass = np.array([0.16, 0.40, 0.11], np.float32) * (1 - m) + np.array([0.64, 0.54, 0.32], np.float32) * m
    landc = grass * (1 - e * 0.5) + np.array([0.45, 0.42, 0.40], np.float32) * (e * 0.5)
    col = np.where(land[..., None], landc, ocean)
    ice = np.clip((np.abs(lat) - 1.12) * 6, 0, 1)[..., None]
    col = col * (1 - ice) + np.array([0.93, 0.96, 1.0], np.float32) * ice
    cl = np.clip((fbm(TH, TW, 6, 31, base=(3, 6)) - 0.48) * 3.2, 0, 1)
    pop = (fbm(TH, TW, 4, 43, base=(4, 8)) > 0.42)
    dots = (np.random.default_rng(41).random((TH, TW)) > 0.93).astype(np.float32)
    dots = np.asarray(Image.fromarray((dots * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.9)), dtype=np.float32) / 255.0 * 4.0
    lights = np.clip(dots, 0, 1) * (land & (np.abs(lat) < 1.1) & pop)
    _T3["earth"] = {"color": col.astype(np.float32), "ocean": (~land).astype(np.float32),
                    "clouds": cl.astype(np.float32), "lights": lights, "TH": TH, "TW": TW}
    return _T3["earth"]


def sun_tex():
    if "sun" not in _T3:
        a, b = fbm(256, 512, 6, 7, base=(4, 8)), fbm(256, 512, 5, 9, base=(16, 32))
        _T3["sun"] = (a * 0.65 + b * 0.35, 256, 512)
    return _T3["sun"]


def moon_tex():
    if "moon" not in _T3:
        import numpy as np
        TH, TW = 256, 512
        base = 0.50 + 0.28 * (fbm(TH, TW, 6, 5, base=(8, 16)) - 0.5)
        maria = np.clip((fbm(TH, TW, 3, 8, base=(2, 4)) - 0.55) * 6, 0, 1)
        tex = base * (1 - 0.45 * maria)
        im = Image.fromarray((tex * 255).astype(np.uint8))
        dr = ImageDraw.Draw(im)
        rnd = random.Random(3)
        for _ in range(260):
            x, y, r = rnd.randint(0, TW), rnd.randint(20, TH - 20), int(rnd.random() ** 2 * 14) + 2
            dr.ellipse([x - r, y - r * 0.9, x + r, y + r * 0.9], fill=int(255 * 0.30))
            dr.ellipse([x - r * 0.75 + r * 0.15, y - r * 0.65, x + r * 0.75, y + r * 0.7], fill=int(255 * 0.46))
            dr.arc([x - r, y - r * 0.9, x + r, y + r * 0.9], 200, 340, fill=int(255 * 0.72), width=1)
        _T3["moon"] = (np.asarray(im, dtype=np.float32) / 255.0, TH, TW)
    return _T3["moon"]


def planet_tex():
    if "planet" not in _T3:
        import numpy as np
        TH, TW = 256, 512
        lat = np.repeat(((0.5 - np.arange(TH) / TH) * np.pi)[:, None], TW, 1)
        warp = fbm(TH, TW, 5, 13, base=(4, 8))
        n = 0.5 + 0.5 * np.sin(lat * 14 + warp * 5.0) * 0.7 + (fbm(TH, TW, 6, 17) - 0.5) * 0.5
        col = lerp_ramp(np.clip(n, 0, 1), [(0, (0.35, 0.18, 0.10)), (0.4, (0.72, 0.45, 0.25)),
                                           (0.7, (0.90, 0.78, 0.55)), (1, (0.96, 0.90, 0.78))])
        _T3["planet"] = (col, TH, TW)
    return _T3["planet"]


def sgrid(R, tilt=0.0):
    """Per-pixel sphere geometry for radius R (cached)."""
    key = ("grid", R, round(tilt, 3))
    if key in _T3:
        return _T3[key]
    import numpy as np
    ys, xs = np.mgrid[-R:R + 1, -R:R + 1].astype(np.float32)
    x, y = xs / R, -ys / R
    r2 = x * x + y * y
    m = r2 < 1.0
    z = np.sqrt(np.clip(1 - r2, 0, 1))
    ct, st = math.cos(tilt), math.sin(tilt)
    ny, nz = y * ct - z * st, y * st + z * ct
    lat = np.arcsin(np.clip(ny, -1, 1))
    lon = np.arctan2(x, nz)
    g = {"m": m, "x": x[m], "y": y[m], "z": z[m], "lat": lat[m], "lon": lon[m], "n": R * 2 + 1}
    g["v01"] = (0.5 - g["lat"] / math.pi)
    _T3[key] = g
    return g


def region(cx, cy, R):
    x0, y0 = cx - R, cy - R
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(RW, cx + R + 1), min(RH, cy + R + 1)
    return fy0, fy1, fx0, fx1, fy0 - y0, fy1 - y0, fx0 - x0, fx1 - x0


def put_sphere(frame, cx, cy, R, mask2d, rgb_flat, alpha=1.0):
    import numpy as np
    fy0, fy1, fx0, fx1, gy0, gy1, gx0, gx1 = region(cx, cy, R)
    if fy1 <= fy0 or fx1 <= fx0:
        return
    full = np.zeros((2 * R + 1, 2 * R + 1, 3), np.float32)
    full[mask2d] = rgb_flat
    mm = mask2d[gy0:gy1, gx0:gx1]
    sub = frame[fy0:fy1, fx0:fx1]
    sub[mm] = sub[mm] * (1 - alpha) + np.clip(full[gy0:gy1, gx0:gx1][mm], 0, 1) * alpha


def halo(frame, cx, cy, R, col, strength, falloff, reach=1.9, L=None, alpha=1.0):
    """Soft glow around a sphere (atmosphere / corona)."""
    import numpy as np
    HR = int(R * reach)
    key = ("halo", HR, R, falloff)
    if key not in _T3:
        ys, xs = np.mgrid[-HR:HR + 1, -HR:HR + 1].astype(np.float32)
        d = np.sqrt(xs * xs + ys * ys) / R
        h = np.where(d > 0.97, np.exp(-(d - 0.97) * falloff), 0).astype(np.float32)
        _T3[key] = (h, xs / (np.sqrt(xs * xs + ys * ys) + 1e-3), -ys / (np.sqrt(xs * xs + ys * ys) + 1e-3))
    h, dx, dy = _T3[key]
    if L is not None:
        h = h * np.clip(0.30 + 0.9 * (dx * L[0] + dy * L[1]), 0.05, 1.2)
    fy0, fy1, fx0, fx1, gy0, gy1, gx0, gx1 = region(cx, cy, HR)
    if fy1 <= fy0 or fx1 <= fx0:
        return
    sub = frame[fy0:fy1, fx0:fx1]
    sub += h[gy0:gy1, gx0:gx1, None] * np.array(col, np.float32) * strength * alpha


def space_bg(i):
    key = ("bg", i % 3)
    if key not in _T3:
        import numpy as np
        rng = np.random.default_rng(100 + i % 3)
        neb = fbm(RH, RW, 4, 50 + i % 3, base=(5, 3), periodic=False)
        tint = [np.array([0.35, 0.15, 0.55]), np.array([0.10, 0.25, 0.55]), np.array([0.50, 0.15, 0.25])][i % 3]
        bg = (neb ** 3)[..., None] * tint * 0.30 + 0.012
        n = 420
        sx, sy = rng.integers(0, RW, n), rng.integers(0, RH, n)
        br = rng.random(n) ** 3 * 0.95 + 0.15
        for x, y, b in zip(sx, sy, br):
            bg[y, x] += b
            if b > 0.7 and 0 < x < RW - 1 and 0 < y < RH - 1:
                bg[y, x - 1] += b * 0.35; bg[y, x + 1] += b * 0.35; bg[y - 1, x] += b * 0.35; bg[y + 1, x] += b * 0.35
        _T3[key] = bg.astype(np.float32)
    return _T3[key]


def draw_earth(frame, cx, cy, R, rot, t, L, tilt=0.4, freeze=0.0, lights_k=1.0):
    import numpy as np
    tex = earth_tex()
    TW, TH = tex["TW"], tex["TH"]
    g = sgrid(R, tilt)
    vi = np.clip(g["v01"] * TH, 0, TH - 1).astype(np.int32)
    ui = (((g["lon"] + rot) / (2 * math.pi) + 0.5) * TW).astype(np.int32) % TW
    col = tex["color"][vi, ui]
    if freeze > 0:
        col = col * (1 - 0.88 * freeze) + np.array([0.92, 0.96, 1.0], np.float32) * 0.88 * freeze
    ocean = tex["ocean"][vi, ui][:, None]
    cl = tex["clouds"][vi, (ui + int(t * 10)) % TW][:, None] * 0.9
    col = col * (1 - cl) + cl
    lam = np.clip(g["x"] * L[0] + g["y"] * L[1] + g["z"] * L[2], 0, 1)[:, None]
    rgb = col * (0.03 + 0.97 * lam ** 0.85)
    hv = np.array(L, np.float32) + np.array([0, 0, 1], np.float32)
    hv /= np.linalg.norm(hv)
    sp = np.clip(g["x"] * hv[0] + g["y"] * hv[1] + g["z"] * hv[2], 0, 1) ** 70
    rgb = rgb + (sp[:, None] * ocean * (1 - cl) * 0.8) * np.array([1, 1, 0.95], np.float32)
    night = np.clip(1 - lam * 5, 0, 1)
    li = tex["lights"][vi, ui][:, None] * night * (1 - cl * 0.85) * lights_k
    rgb = rgb + li * np.array([1.0, 0.78, 0.35], np.float32) * 1.3
    rim = ((1 - g["z"]) ** 2.6 * np.clip(0.2 + lam[:, 0] * 1.3, 0, 1))[:, None]
    rgb = rgb + rim * np.array([0.25, 0.52, 1.0], np.float32) * 1.2
    halo(frame, cx, cy, R, (0.20, 0.45, 1.0), 0.55, 11.0, 1.35, L)
    put_sphere(frame, cx, cy, R, g["m"], rgb)


def draw_sun(frame, cx, cy, R, t, a=1.0):
    import numpy as np
    tex, TH, TW = sun_tex()
    g = sgrid(R, 0.0)
    vi = np.clip(g["v01"] * TH, 0, TH - 1).astype(np.int32)
    ui = (((g["lon"] + t * 0.12) / (2 * math.pi) + 0.5) * TW).astype(np.int32) % TW
    n = tex[vi, ui]
    n = np.clip((n - 0.5) * 2.4 + 0.5 + 0.08 * np.sin(t * 2 + n * 12), 0, 1)
    c = lerp_ramp(n, [(0, (0.60, 0.10, 0.0)), (0.45, (1.0, 0.45, 0.04)), (0.8, (1.0, 0.80, 0.25)), (1, (1.0, 0.97, 0.75))])
    limb = (g["z"] ** 0.5)[:, None]
    rgb = c * (0.45 + 0.75 * limb)
    pulse = 1 + 0.06 * math.sin(t * 3)
    halo(frame, cx, cy, R, (1.0, 0.50, 0.12), 0.95 * pulse, 3.4, 2.4, None, a)
    halo(frame, cx, cy, R, (1.0, 0.85, 0.5), 0.55, 9.0, 1.4, None, a)
    put_sphere(frame, cx, cy, R, g["m"], rgb, a)


def draw_moon(frame, cx, cy, R, rot, L, a=1.0):
    import numpy as np
    tex, TH, TW = moon_tex()
    g = sgrid(R, 0.1)
    vi = np.clip(g["v01"] * TH, 0, TH - 1).astype(np.int32)
    ui = (((g["lon"] + rot) / (2 * math.pi) + 0.5) * TW).astype(np.int32) % TW
    v = tex[vi, ui][:, None]
    lam = np.clip(g["x"] * L[0] + g["y"] * L[1] + g["z"] * L[2], 0, 1)[:, None]
    rgb = v * (0.025 + 1.15 * lam ** 0.8) * np.array([1.0, 0.98, 0.94], np.float32)
    halo(frame, cx, cy, R, (0.8, 0.85, 1.0), 0.22, 10.0, 1.3, L, a)
    put_sphere(frame, cx, cy, R, g["m"], rgb, a)


def draw_planet(frame, cx, cy, R, rot, L, tilt=0.35):
    import numpy as np
    col, TH, TW = planet_tex()
    ring_t = 0.30
    key = ("ring", R)
    if key not in _T3:
        RR = int(R * 2.5)
        ys, xs = np.mgrid[-RR:RR + 1, -RR:RR + 1].astype(np.float32)
        rr = np.sqrt((xs / R) ** 2 + (ys / R / ring_t) ** 2)
        _T3[key] = (RR, ys, rr)
    RR, ys, rr = _T3[key]
    band = 0.55 + 0.45 * np.sin(rr * 46) * np.sin(rr * 13 + 1)
    inring = ((rr > 1.38) & (rr < 2.35)).astype(np.float32) * np.clip(band, 0.15, 1) * 0.9
    ringcol = np.array([0.82, 0.72, 0.55], np.float32)

    def paint_ring(front):
        sel = (ys >= 0) if front else (ys < 0)
        al = inring * sel
        fy0, fy1, fx0, fx1, gy0, gy1, gx0, gx1 = region(cx, cy, RR)
        if fy1 <= fy0 or fx1 <= fx0:
            return
        sub = frame[fy0:fy1, fx0:fx1]
        a2 = al[gy0:gy1, gx0:gx1, None]
        sub[:] = sub * (1 - a2) + ringcol * a2

    g = sgrid(R, tilt)
    vi = np.clip(g["v01"] * TH, 0, TH - 1).astype(np.int32)
    ui = (((g["lon"] + rot) / (2 * math.pi) + 0.5) * TW).astype(np.int32) % TW
    lam = np.clip(g["x"] * L[0] + g["y"] * L[1] + g["z"] * L[2], 0, 1)[:, None]
    rgb = col[vi, ui] * (0.05 + 1.0 * lam ** 0.85)
    rgb = rgb + ((1 - g["z"]) ** 3 * 0.35)[:, None] * np.array([1.0, 0.8, 0.5], np.float32) * lam
    halo(frame, cx, cy, R, (1.0, 0.7, 0.4), 0.22, 10.0, 1.3, L)
    paint_ring(False)
    put_sphere(frame, cx, cy, R, g["m"], rgb)
    paint_ring(True)


def draw_black_hole(frame, cx, cy, R0, t):
    import numpy as np
    key = ("bh", cx, cy, R0)
    if key not in _T3:
        ys, xs = np.mgrid[0:RH, 0:RW].astype(np.float32)
        dx, dy = xs - cx, ys - cy
        r = np.sqrt(dx * dx + dy * dy) + 1e-3
        rs = np.maximum(r - (R0 * 1.15) ** 2 / r, 0)          # lensing: where the light really came from
        sx = np.clip(cx + dx / r * rs, 0, RW - 1).astype(np.int32)
        sy = np.clip(cy + dy / r * rs, 0, RH - 1).astype(np.int32)
        _T3[key] = (sx, sy, dx / R0, dy / R0, r / R0, np.arctan2(dy, dx))
    sx, sy, X, Y, Rr, th = _T3[key]
    bg = frame.copy()
    frame[:] = bg[sy, sx]
    swirl = 0.70 + 0.30 * np.sin(th * 5 - t * 3.2 - Rr * 7)
    dop = np.clip(0.80 + 0.35 * X / np.maximum(Rr, 1.0), 0.3, 1.5)
    band = np.exp(-(Y / (0.07 + 0.045 * Rr)) ** 2) * (Rr > 1.12) * np.clip((3.8 - Rr) / 1.4, 0, 1)
    I = np.exp(-(Rr - 1.1) * 0.55) * band * 1.5
    arch_up = (Y < 0) & (Rr > 1.0) & (Rr < 2.1)
    I = I + np.exp(-(Rr - 1.0) * 2.4) * arch_up * 1.5
    arch_dn = (Y >= 0) & (Rr > 1.0) & (Rr < 1.5)
    I = I + np.exp(-(Rr - 1.0) * 3.5) * arch_dn * 1.0
    I = I * swirl * dop
    col = lerp_ramp(np.clip(I * 0.8, 0, 1), [(0, (0.5, 0.08, 0.0)), (0.35, (1.0, 0.42, 0.06)), (0.7, (1.0, 0.80, 0.38)), (1, (1.0, 0.98, 0.90))])
    frame += col * np.clip(I, 0, 1.6)[..., None]
    glow_a = np.exp(-(Rr - 1.0) * 1.6) * (Rr > 1.0) * 0.20
    frame += glow_a[..., None] * np.array([1.0, 0.5, 0.15], np.float32)
    frame[Rr < 1.0] = 0.0


def render3d(kind, t, p, txt, i):
    import numpy as np
    frame = space_bg(i).copy()
    frame = np.roll(frame, int(t * 2), axis=0)
    cx, cy = RW // 2, 330
    vanish = has(txt, r"vanish|disappear|gone")
    a = max(0.0, 1 - p * 1.25) if vanish else 1.0
    if kind == "sun":
        draw_sun(frame, cx, cy, int(165 + 28 * p), t, a)
    elif kind == "moon":
        L = [(0.85, 0.25, 0.45), (-0.8, 0.3, 0.5), (0.2, 0.8, 0.55)][i % 3]
        draw_moon(frame, cx, cy, int(190 + 20 * p), 0.3 + t * 0.05 + i, L, a)
    elif kind == "bh":
        draw_black_hole(frame, cx, cy, 72, t)
    elif kind == "planet":
        draw_planet(frame, cx, cy + 20, int(135 + 20 * p), t * 0.25 + i, [(-0.7, 0.35, 0.6), (0.7, 0.3, 0.65), (0.0, 0.7, 0.7)][i % 3])
    else:
        stopped = has(txt, r"stop|halt|standing still")
        night = has(txt, r"dark|night|lights|power|grid|city|cities|internet|network|people|human|billion|phone|bank")
        fast = has(txt, r"clock|time\b|hour|week|year|\bday")
        speed = 0.0 if stopped else (1.6 if fast else 0.45)
        freeze = p if has(txt, r"freez|frozen|\bice\b|cold|snow") else 0.0
        blackout = has(txt, r"out|fail|stop|blackout|vanish|disappear|gone")
        lk = max(0.0, 1 - p * 1.2) if (night and blackout) else 1.0
        if night:
            L = [(-0.95, 0.12, -0.28), (0.95, 0.1, -0.3), (0.0, 0.9, -0.4)][i % 3]
        else:
            L = [(-0.65, 0.4, 0.65), (0.7, 0.3, 0.65), (0.1, 0.75, 0.65), (-0.9, 0.0, 0.45)][i % 4]
        n = np.array(L, np.float32)
        n = (n / np.linalg.norm(n)).tolist()
        draw_earth(frame, cx, cy, int(185 + 30 * p), i * 1.7 + speed * t, t, n, 0.4, freeze, lk)
    img = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    if kind == "bh" and has(txt, r"fell|fall|stretch|spaghett|you "):
        d = ImageDraw.Draw(img)
        sx_, sy_ = (cx + 230 - 170 * p) * 2, (cy - 110 + 100 * p) * 2
        wd, ht = 26 * (1 - 0.6 * p), 26 + 180 * p
        d.ellipse([sx_ - wd, sy_ - ht / 2, sx_ + wd, sy_ + ht / 2], fill=(235, 245, 255))
    return img


KIND3D = {"sun": "sun", "fire": "sun", "moon": "moon", "black_hole": "bh", "brain": "planet", "cosmos": "planet"}


def pick_3d(scene_text, title=""):
    return "3d:" + KIND3D.get(pick_anim(scene_text, title), "earth")


def kenburns(img, p, i):
    """Slow zoom and drift over a W x H image. p goes 0..1 during the scene."""
    z = max(1.0, 1 + 0.14 * p if i % 2 == 0 else 1.14 - 0.14 * p)
    bw, bh = W / z, H / z
    drift = (p - 0.5) * (0.3 if i % 2 else -0.3)
    x0 = max(0.0, (W - bw) * (0.5 + drift))
    y0 = max(0.0, (H - bh) / 2)
    return img.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + bw, y0 + bh))


def has_images():
    return IMAGES.exists() and any(p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") for p in IMAGES.glob("*"))


def make_bg_func(scene_imgs, scene_texts, total, scene_anims=None, words=None):
    """Returns f(t) -> background frame: built-in animations, scene pictures, or moving stars."""
    if scene_imgs or scene_anims:
        bounds = []
        if words:
            for i in range(len(scene_texts)):
                last_word = min(i * 2 + 1, len(words) - 1)
                bounds.append(min(total, words[last_word][1] + words[last_word][2]))
        else:
            weights = [max(len(t), 1) for t in scene_texts]
            acc = 0
            for weight in weights:
                acc += weight
                bounds.append(total * acc / sum(weights))

        def draw_scene(s, tl, p):
            img = scene_imgs[s] if scene_imgs else None
            if img is not None:
                return kenburns(img, p, s)
            return anim_frame(scene_anims[s], tl, p, scene_texts[s], s)

        def f(t):
            s = next((i for i, b in enumerate(bounds) if t < b), len(bounds) - 1)
            start = bounds[s - 1] if s else 0
            span = max(bounds[s] - start, 0.01)
            frame = draw_scene(s, t - start, min(max((t - start) / span, 0), 1))
            if s and t - start < 0.3:                      # quick cross-fade between scenes
                pstart = bounds[s - 2] if s > 1 else 0
                prev = draw_scene(s - 1, bounds[s - 1] - pstart, 1.0)
                frame = Image.blend(prev, frame, (t - start) / 0.3)
            return frame
        return f
    bgs = load_backgrounds()
    rnd = random.Random(7)
    stars = [] if has_images() else [(rnd.randint(0, W), rnd.randint(0, H), rnd.randint(40, 160),
                                      rnd.choice([2, 3, 4, 6])) for _ in range(70)]

    def f(t):
        bg = bgs[min(int(t / total * len(bgs)), len(bgs) - 1)].copy()
        d = ImageDraw.Draw(bg)
        for x, y0, sp, r in stars:
            y = (y0 - sp * t) % H
            d.ellipse([x - r, y - r, x + r, y + r], fill=(235, 235, 255))
        return bg
    return f


def render(title, words, mp3_path, mp4_path, clip=None, scene_imgs=None, scene_texts=None, scene_anims=None):
    """Draw captions frame by frame over: scene pictures, a stock clip, or moving stars."""
    total = words[-1][1] + words[-1][2] + 0.8
    n_frames = int(total * FPS)
    groups = group_words(words)
    starts = [w[1] for w in words]
    dur = f"{n_frames / FPS:.3f}"
    if clip and not scene_imgs and not scene_anims:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(clip),
               "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
               "-i", str(mp3_path), "-filter_complex",
               f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
               f"fps={FPS},eq=brightness=-0.18[b];[b][1:v]overlay=shortest=1,format=yuv420p[v]",
               "-map", "[v]", "-map", "2:a", "-af", "apad", "-c:v", "libx264", "-preset", "veryfast",
               "-c:a", "aac", "-t", dur, str(mp4_path)]
        bgf, mode = (lambda t: None), "RGBA"
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(mp3_path),
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-af", "apad", "-c:a", "aac", "-t", dur, str(mp4_path)]
        bgf, mode = make_bg_func(scene_imgs, scene_texts or [], total, scene_anims, words), "RGB"
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for f in range(n_frames):
            t = f / FPS
            idx = max([i for i, s in enumerate(starts) if s <= t], default=None)
            frame = draw_frame(bgf(t), title, words, groups, idx)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed. Is ffmpeg installed and on PATH?")


# ---------- 4. upload ----------
def validate_video(path):
    """Fail safely before upload if FFmpeg created a corrupt or non-Shorts file."""
    if not path.exists() or path.stat().st_size < 100_000:
        raise RuntimeError("Rendered video is missing or unexpectedly small.")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30
    )
    if probe.returncode != 0:
        raise RuntimeError("ffprobe could not read the rendered video: " + (probe.stderr or "")[-800:])
    info = json.loads(probe.stdout or "{}")
    video = next((x for x in info.get("streams", []) if x.get("codec_type") == "video"), None)
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    if not video or video.get("width") != W or video.get("height") != H:
        raise RuntimeError("Rendered video must be 1080x1920 vertical video.")
    if not 5 <= duration <= 180:
        raise RuntimeError(f"Rendered video duration is outside the expected Shorts range: {duration:.1f}s.")
    print(f"Video validation passed: 1080x1920, {duration:.1f}s, {path.stat().st_size:,} bytes.")


def upload(mp4_path, title, description, tags, privacy="private"):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    token = HERE / "token.json"
    if os.environ.get("YOUTUBE_TOKEN_JSON"):          # used by the GitHub Action
        token.write_text(os.environ["YOUTUBE_TOKEN_JSON"])
    creds = Credentials.from_authorized_user_file(token, scopes) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret = HERE / "client_secret.json"
            if not secret.exists():
                raise FileNotFoundError("client_secret.json not found next to this script (see README)")
            creds = InstalledAppFlow.from_client_secrets_file(str(secret), scopes).run_local_server(port=0)
        token.write_text(creds.to_json())
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title[:100], "description": description, "tags": tags,
                        "categoryId": "27"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(mp4_path), resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  uploading {int(status.progress() * 100)}%")
    video_id = resp["id"]
    try:
        published = yt.videos().list(part="status", id=video_id).execute()
        actual = (published.get("items") or [{}])[0].get("status", {}).get("privacyStatus", "unknown")
        print(f"YouTube visibility check: requested={privacy}, actual={actual}.")
        if actual != privacy:
            print("WARNING: YouTube did not apply the requested visibility. Check YouTube Studio and API project verification.")
    except Exception as exc:
        print("WARNING: Could not verify YouTube visibility automatically:", exc)
    return video_id


# ---------- 5. trends, topic writing, stock video ----------
def http_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "auto-shorts"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_youtube_titles(data):
    return [html.unescape(i["snippet"]["title"]) for i in data.get("items", [])]


def find_trending(days=7, n=15):
    """Rank recent What If? videos by view velocity and engagement over a rolling window."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("No YOUTUBE_API_KEY: skipping trend search.")
        return []

    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    searches = [
        '"what if" science',
        '"what would happen if"',
        '"what if" earth OR space OR sun',
    ]
    found = {}

    try:
        for term in searches:
            params = {
                "part": "snippet", "type": "video", "q": term,
                "order": "viewCount", "publishedAfter": after,
                "videoDuration": "short", "relevanceLanguage": "en", "regionCode": "US",
                "maxResults": min(n, 25), "key": key,
            }
            data = http_json(
                "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
            )
            for item in data.get("items", []):
                video_id = item.get("id", {}).get("videoId")
                if not video_id:
                    continue
                snippet = item.get("snippet", {})
                found[video_id] = {
                    "id": video_id,
                    "title": html.unescape(snippet.get("title", "")),
                    "published": snippet.get("publishedAt", ""),
                    "channel": html.unescape(snippet.get("channelTitle", "")),
                }

        ids = list(found)
        stats_by_id = {}
        for offset in range(0, len(ids), 50):
            batch = ids[offset:offset + 50]
            stats = http_json(
                "https://www.googleapis.com/youtube/v3/videos?" +
                urllib.parse.urlencode({
                    "part": "statistics", "id": ",".join(batch), "key": key
                })
            )
            for video in stats.get("items", []):
                stats_by_id[video["id"]] = video.get("statistics", {})

        now = datetime.now(timezone.utc)
        ranked = []
        for video_id, item in found.items():
            try:
                published = datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            age_hours = max((now - published).total_seconds() / 3600, 1.0)
            stats = stats_by_id.get(video_id, {})
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            velocity = views / age_hours
            engagement = (likes + comments) / max(views, 1)
            score = math.log1p(velocity) + min(engagement, 0.20) * 8
            item.update({
                "views": views, "likes": likes, "comments": comments,
                "age_hours": age_hours, "views_per_hour": velocity,
                "score": score,
            })
            ranked.append(item)

        ranked.sort(key=lambda x: x["score"], reverse=True)
        result = [
            (f'{v["title"]} | {v["views"]:,} views in {v["age_hours"]:.1f}h '
             f'({v["views_per_hour"]:.1f} views/hour), '
             f'{v["likes"]:,} likes, channel: {v["channel"]}, '
             f'https://youtube.com/watch?v={v["id"]}')
            for v in ranked[:n]
        ]
        print(f"Found {len(result)} recent What If? trend candidates from the last {days} days.")
        return result
    except Exception as e:
        print("Trend search failed:", e)
        return []

def parse_topics(text):
    """Turn the model's reply into a clean list of {title, script, keywords}."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    out = []
    for t in json.loads(text):
        title, script = str(t["title"]).strip(), str(t["script"]).strip()
        if title and 20 <= len(script.split()) <= 120:
            out.append({"title": title, "script": script, "keywords": str(t.get("keywords", "")).strip()})
    return out


def gemini_text(prompt, max_output_tokens=4000):
    """Generate text with the Google Gemini Developer API."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your environment or GitHub Actions secrets.")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        contents=prompt,
        config={"max_output_tokens": max_output_tokens, "response_mime_type": "application/json"},
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")
    return response.text.strip()


def add_topics(topics, n, trends=None, front=False):
    """Ask Gemini for new original scripts inspired by current trends."""
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set, so no new topics were written.")
        return topics
    prompt = (
        f"Write {n} NEW YouTube Shorts scripts for a 'What if' science channel.\n"
        "Target audience: viewers in the United States. Use natural, conversational American English, "
        "clear pronunciation-friendly wording, and examples familiar to US viewers when relevant; "
        "keep the science globally understandable and avoid forced slang. "
        "Rules: 55-75 spoken words; open with a surprising, specific hook in the first 2 seconds; "
        "use short, natural American English sentences that sound good when spoken aloud; "
        "build curiosity with a clear beginning, escalating consequence, and satisfying final reveal; "
        "keep claims scientifically accurate, never invent statistics, and say about when uncertain; "
        "avoid filler, repeated phrases, awkward abbreviations, and hard-to-pronounce number strings; "
        "make the title compelling and accurate, ideally 35-65 characters, with no misleading clickbait; "
        "the last sentence is exactly: Follow for more what if stories.\n"
        "Also give 'keywords': 2 or 3 plain English words to search stock footage for the video background "
        "(example: 'planet earth space').\n"
        "Do NOT repeat these topics: " + "; ".join(t["title"] for t in topics) + "\n"
    )
    if trends:
        prompt += ("These 'what if' videos are trending on YouTube this week: " + " | ".join(trends) +
                   "\nPick the topic idea that is trending most, and write an ORIGINAL script about it "
                   "with your own wording and a fresh angle. Never copy their titles or wording.\n")
    prompt += 'Reply with ONLY a JSON array like [{"title": "What if ...?", "script": "...", "keywords": "..."}]'
    generated = gemini_text(prompt, max_output_tokens=4000)
    have = {t["title"].lower() for t in topics}
    new = [t for t in parse_topics(generated) if t["title"].lower() not in have][:n]
    print(f"Added {len(new)} new topics.")
    return (new + topics) if front else (topics + new)
def refill(topics, min_left=3, batch=7):
    if sum(1 for t in topics if not t.get("done")) >= min_left:
        return topics
    return add_topics(topics, batch)


def split_scenes(script, min_words=10, max_scenes=7):
    """Group sentences into scenes (one picture each)."""
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", script.strip()) if x.strip()]
    scenes, cur = [], ""
    for sent in sents:
        cur = (cur + " " + sent).strip()
        if len(cur.split()) >= min_words:
            scenes.append(cur)
            cur = ""
    if cur:
        if scenes and len(cur.split()) < min_words:
            scenes[-1] += " " + cur
        else:
            scenes.append(cur)
    while len(scenes) > max_scenes:                      # merge the two shortest neighbours
        i = min(range(len(scenes) - 1), key=lambda k: len(scenes[k]) + len(scenes[k + 1]))
        scenes[i:i + 2] = [scenes[i] + " " + scenes[i + 1]]
    return scenes


def split_visual_pairs(script):
    """Create one narration-synchronised visual beat for every two spoken words."""
    tokens = re.findall(r"\S+", script.strip())
    return [" ".join(tokens[i:i + 2]).strip() for i in range(0, len(tokens), 2) if tokens[i:i + 2]]


def download(url, path, headers=None, timeout=150):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "auto-shorts"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        f.write(r.read())
    Image.open(path).verify()                            # make sure it is a real picture


STOP = set("""about after again also and any are because been before being between both but can could did does
doing down during each even every first from had has have having here how into its just keep like make more most
much must now off once only other our out over own same she should some such than that the their them then there
these they this those through too under until very was were what when where which while who will with would you your
one two three four five six seven eight nine ten would still""".split())


def simple_query(text, n=3):
    """Offline fallback: pick the longest meaningful words of a scene as a photo search."""
    words = [w for w in re.findall(r"[a-zA-Z]+", text.lower()) if w not in STOP and len(w) > 3]
    return " ".join(sorted(set(words), key=lambda w: -len(w))[:n])


CAT_QUERY = {"sun": "sun solar flare", "earth": "planet earth from space", "moon": "moon surface",
             "black_hole": "black hole", "ocean": "ocean waves", "ice": "glacier ice arctic",
             "fire": "wildfire flames", "network": "earth at night city lights",
             "brain": "astronaut sleeping space station", "gravity": "astronaut floating space station",
             "crowd": "earth at night city lights", "clock": "earth rotation timelapse",
             "city": "earth at night city lights", "cosmos": "galaxy nebula"}
CREDITS = []


def cat_query(scene_text, title=""):
    return CAT_QUERY[pick_anim(scene_text, title)]


# ---------- scene planning (Gemini) + drawn illustrations ----------
def plan_scenes(texts, title):
    """Create photo search phrases and optional drawings with Gemini."""
    plan = [{"query": cat_query(t, title), "art": None} for t in texts]
    if not os.environ.get("GEMINI_API_KEY"):
        return plan
    try:
        listing = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
        prompt = (
            f"Video title: {title}\nVoiceover visual beats in exact order (each beat is exactly two consecutive spoken words):\n{listing}\n\n"
            "For EACH two-word beat, create a concrete visual that directly depicts those words in the context of the title and surrounding story. Do not use merely related general-topic footage. If the pair contains a pronoun or helper word, infer its actual referent/action from nearby narration. Never use generic filler footage. For EACH beat give:\n"
            '- "query": 3-5 plain English words to find a REAL MOVING VIDEO CLIP showing the exact action or subject '
            "(examples: 'earth rotating in space', 'city traffic time lapse', 'cracked dry earth close up', "
            "'solar flare erupting from sun'). Prefer concrete visible actions, environments, and camera subjects; "
            "do not use abstract words, generic people, or a query that does not match the scene narration.\n"
            '- "art": a simple, bold, flat illustration as drawing steps on a canvas '
            "1000 wide x 1778 tall (x goes right, y goes down). Put the main subject big, between y=200 and y=950. "
            "Format: {\"bg\":[\"#top color\",\"#bottom color\"],\"shapes\":[{\"t\":\"circle\",\"x\":500,\"y\":600,\"r\":220,\"fill\":\"#ffcc00\",\"glow\":true}]} . "
            "Use 10-25 shapes, bright colors, and a background that fits the topic.\n"
            "Reply with ONLY a JSON array with one object per scene: [{\"query\":\"...\",\"art\":{...}}]"
        )
        text = gemini_text(prompt, max_output_tokens=9000)
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(text)
        for i in range(len(texts)):
            item = data[i] if i < len(data) and isinstance(data[i], dict) else {}
            plan[i] = {"query": str(item.get("query") or plan[i]["query"]),
                       "art": item.get("art") if isinstance(item.get("art"), dict) else None}
        print("Scene plan ready (scene-specific moving-footage searches + illustration fallbacks).")
    except Exception as e:
        print("Scene planning failed, using simple searches:", e)
    return plan
def hexcol(c, default=(255, 255, 255)):
    try:
        c = str(c).lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def render_art(spec):
    """Draw Gemini's illustration steps with Pillow (no internet needed)."""
    SS = 2
    w, h = W * SS, H * SS
    sx, sy = w / 1000, h / 1778
    bg = spec.get("bg") or ["#0b1030", "#3a1c71"]
    top, bot = hexcol(bg[0]), hexcol(bg[-1])
    img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(0, h, 6):
        t = y / h
        d.rectangle([0, y, w, y + 6], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    glows = 0
    for sh in (spec.get("shapes") or [])[:60]:
        try:
            t, col = sh.get("t"), hexcol(sh.get("fill", "#ffffff"))
            if t == "circle":
                x, y, r = sh["x"] * sx, sh["y"] * sy, sh["r"] * sx
                if sh.get("glow") and glows < 3:
                    glows += 1
                    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    ImageDraw.Draw(layer).ellipse([x - r * 1.5, y - r * 1.5, x + r * 1.5, y + r * 1.5], fill=col + (110,))
                    img = Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(r * 0.4)))
                    d = ImageDraw.Draw(img)
                d.ellipse([x - r, y - r, x + r, y + r], fill=col + (255,))
            elif t == "rect":
                x, y = sh["x"] * sx, sh["y"] * sy
                d.rectangle([x, y, x + sh["w"] * sx, y + sh["h"] * sy], fill=col + (255,))
            elif t == "poly":
                d.polygon([(px * sx, py * sy) for px, py in sh["pts"]], fill=col + (255,))
            elif t == "line":
                d.line([(px * sx, py * sy) for px, py in sh["pts"]], fill=col + (255,), width=max(2, int(sh.get("w", 6) * sx)))
            elif t == "text":
                d.text((sh["x"] * sx, sh["y"] * sy), str(sh["s"])[:30], font=get_font(int(sh.get("size", 100) * sx)),
                       fill=col + (255,), anchor="mm")
        except Exception:
            continue
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


def prep_photo(path, dark=0.8):
    """Portrait photos fill the screen; wide photos sit on a blurred copy of themselves."""
    img = Image.open(path).convert("RGB")
    if img.width / img.height <= 0.75:
        return cover(path, dark)
    bg = cover(path, 0.45).filter(ImageFilter.GaussianBlur(25))
    nh = int(W * img.height / img.width)
    pic = ImageEnhance.Brightness(img.resize((W, nh), Image.LANCZOS)).enhance(dark)
    bg.paste(pic, (0, int(H * 0.36 - nh / 2)))
    return bg


# ---------- picture sources ----------
def fetch_pollinations(prompt, path, seed):
    try:
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:600]) +
               f"?width=768&height=1344&model=flux&nologo=true&seed={seed}")
        download(url, path)
        return True, ""
    except Exception as e:
        return False, str(e)


def fetch_pexels_photo(query, path, pick=0):
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return False
    try:
        q = urllib.parse.urlencode({"query": query, "orientation": "portrait", "per_page": 6})
        photos = http_json("https://api.pexels.com/v1/search?" + q,
                           {"Authorization": key, "User-Agent": "auto-shorts"}).get("photos", [])
        if not photos:
            return False
        download(photos[pick % len(photos)]["src"]["portrait"], path)
        return True
    except Exception as e:
        print("   Pexels failed:", e)
        return False


def fetch_pixabay_photo(query, path, pick=0):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not query:
        return False
    try:
        q = urllib.parse.urlencode({"key": key, "q": query, "image_type": "photo", "orientation": "vertical",
                                    "per_page": 10, "safesearch": "true"})
        hits = http_json("https://pixabay.com/api/?" + q).get("hits", [])
        if not hits:
            return False
        download(hits[pick % len(hits)]["largeImageURL"], path)
        return True
    except Exception as e:
        print("   Pixabay failed:", e)
        return False


def pick_nasa_url(urls):
    jpgs = [u for u in urls if u.lower().endswith((".jpg", ".jpeg"))]
    best = next((u for u in jpgs if "~large" in u or "~medium" in u), jpgs[0] if jpgs else None)
    return best.replace("http://", "https://") if best else None


def fetch_nasa_photo(query, path, pick=0):
    """NASA image library: free, no key, great for space/Earth/science topics."""
    if not query:
        return False
    try:
        data = http_json("https://images-api.nasa.gov/search?" +
                         urllib.parse.urlencode({"q": query, "media_type": "image"}))
        items = data["collection"]["items"][:6]
        if not items:
            return False
        url = pick_nasa_url(http_json(items[pick % len(items)]["href"].replace("http://", "https://")))
        if not url:
            return False
        download(url, path)
        return True
    except Exception as e:
        print("   NASA failed:", e)
        return False


def fetch_scene_visuals(scenes, plan, slug):
    """One realistic picture per scene. AI photo -> Pixabay -> NASA photo. None = use an animation."""
    imgs, how, poll_ok = [], [], True
    for i, text in enumerate(scenes):
        q = plan[i]["query"] or simple_query(text)
        path = OUT / f"{slug}_scene{i}.jpg"
        img, src = None, None
        clean = re.sub(r"Follow for more.*$", "", text, flags=re.I).strip() or q
        if poll_ok:
            ok, err = fetch_pollinations(f"photorealistic, {clean} {q}, ultra realistic, natural lighting, "
                                         "sharp focus, high detail, no text, no words", path, i * 11 + 3)
            if ok:
                img, src = prep_photo(path, 0.9), "AI photo"
                time.sleep(16)                      # free tier: about 1 picture per 15 seconds
            else:
                poll_ok = False                     # don't waste time on the other scenes
                print("   AI picture service not working:", err[:120])
        if img is None and fetch_pixabay_photo(q, path, i):
            img, src = prep_photo(path, 0.9), "Pixabay photo"
        if img is None and fetch_pexels_photo(q, path, i):
            img, src = prep_photo(path, 0.9), "Pexels photo"
        if img is None and fetch_nasa_photo(q, path, i):
            img, src = prep_photo(path, 0.9), "NASA photo"
            if "Images: NASA Image and Video Library (images.nasa.gov)" not in CREDITS:
                CREDITS.append("Images: NASA Image and Video Library (images.nasa.gov)")
        if img is None and plan[i].get("art"):
            try:
                img, src = render_art(plan[i]["art"]), "drawn illustration"
            except Exception as e:
                print("   drawing failed:", e)
        imgs.append(img)
        how.append(src or "built-in animation")
        print(f"  scene {i + 1}/{len(scenes)} [{q}] -> {how[-1]}")
    if not any(imgs):
        print("WARNING: no real pictures could be downloaded (check internet). Using built-in animations.")
        return None
    return imgs


def pick_video_url(data):
    """Choose a portrait HD mp4 link from a Pexels video-search reply."""
    best = None
    for v in data.get("videos", []):
        for f in v.get("video_files", []):
            w, h = f.get("width") or 0, f.get("height") or 0
            if f.get("file_type") == "video/mp4" and h > w and h >= 1280:
                if best is None or h < best[0]:
                    best = (h, f["link"])
        if best:
            return best[1]
    return None


def fetch_clip(keywords, out_path):
    """Download a free vertical stock video (Pexels). Returns the path, or None."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not keywords:
        return None
    try:
        q = urllib.parse.urlencode({"query": keywords, "orientation": "portrait", "per_page": 8})
        url = pick_video_url(http_json("https://api.pexels.com/videos/search?" + q,
                                       {"Authorization": key, "User-Agent": "auto-shorts"}))
        if not url:
            print("No stock clip found for:", keywords)
            return None
        req = urllib.request.Request(url, headers={"User-Agent": "auto-shorts"})
        with urllib.request.urlopen(req, timeout=120) as r, open(out_path, "wb") as f:
            f.write(r.read())
        return out_path
    except Exception as e:
        print("Stock clip failed, using plain background:", e)
        return None

def fetch_pixabay_clip(keywords, out_path):
    """Download a scene-matched free stock video from Pixabay."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not keywords:
        return None
    try:
        params = urllib.parse.urlencode({
            "key": key, "q": keywords, "video_type": "film",
            "per_page": 12, "safesearch": "true"
        })
        hits = http_json("https://pixabay.com/api/videos/?" + params).get("hits", [])
        if not hits:
            print("No Pixabay video found for:", keywords)
            return None
        # Prefer the best available rendition; portrait is preferred when available,
        # otherwise use a good landscape clip and crop it to the Shorts frame.
        candidates = []
        for hit in hits:
            videos = hit.get("videos", {})
            for size in ("large", "medium", "small"):
                item = videos.get(size, {})
                url = item.get("url")
                w, h = item.get("width") or 0, item.get("height") or 0
                if url:
                    candidates.append((1 if h > w else 0, w * h, url))
                    break
        if not candidates:
            return None
        url = sorted(candidates, reverse=True)[0][2]
        req = urllib.request.Request(url, headers={"User-Agent": "auto-shorts"})
        with urllib.request.urlopen(req, timeout=120) as response, open(out_path, "wb") as output:
            output.write(response.read())
        return out_path
    except Exception as e:
        print("Pixabay video search failed:", e)
        return None


def fetch_scene_videos(scenes, plan, slug):
    """Get a separate scene-matched stock video, preferring Pexels then Pixabay."""
    clips = []
    if not os.environ.get("PEXELS_API_KEY") and not os.environ.get("PIXABAY_API_KEY"):
        print("No stock video API key is configured; using image/animation fallbacks.")
        return None
    for i, scene in enumerate(scenes):
        query = (plan[i].get("query") or simple_query(scene) or scene)[:100]
        path = OUT / f"{slug}_video_scene{i}.mp4"
        clip = fetch_clip(query, path) if os.environ.get("PEXELS_API_KEY") else None
        if not clip and os.environ.get("PIXABAY_API_KEY"):
            clip = fetch_pixabay_clip(query, path)
        if clip:
            clips.append(str(clip))
            print(f"  scene video {i + 1}/{len(scenes)} -> {query}")
        else:
            clips.append(None)
    return clips if any(clips) else None


def render_with_scene_videos(title, words, mp3_path, mp4_path, clips, scene_texts, scene_imgs=None):
    """Build a scene-matched video reel, then use the stable caption renderer."""
    total = words[-1][1] + words[-1][2] + 0.8
    weights = [max(len(t.split()), 1) for t in scene_texts]
    transition = 0.22
    timeline_total = total + transition * max(0, len(scene_texts) - 1)
    durations = [timeline_total * w / sum(weights) for w in weights]
    if not any(clips):
        return False

    # Normalize each scene in one FFmpeg filter graph. Avoid piping decoded
    # 1080x1920 raw frames between two FFmpeg processes (the old broken-pipe bug).
    reel_path = OUT / f"{mp4_path.stem}_scene_reel.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    filters, labels = [], []
    for i in range(len(scene_texts)):
        if i < len(clips) and clips[i]:
            cmd += ["-stream_loop", "-1", "-i", str(clips[i])]
        elif scene_imgs and i < len(scene_imgs) and scene_imgs[i] is not None:
            image_path = OUT / f"{mp4_path.stem}_fallback_scene{i}.jpg"
            scene_imgs[i].save(image_path, quality=92)
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{durations[i]:.3f}",
                    "-i", str(image_path)]
        else:
            # Keep the sequence complete without substituting unrelated footage.
            fallback = OUT / f"{mp4_path.stem}_blank_scene{i}.jpg"
            Image.new("RGB", (W, H), (12, 18, 38)).save(fallback, quality=90)
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{durations[i]:.3f}",
                    "-i", str(fallback)]

        filters.append(
            f"[{i}:v]trim=duration={durations[i]:.3f},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"setsar=1,fps={FPS},settb=AVTB,format=yuv420p[v{i}]"
        )
        labels.append(f"[v{i}]")

    if len(labels) == 1:
        final_label = labels[0]
    else:
        previous = labels[0]
        for i in range(1, len(labels)):
            next_label = f"[xf{i}]"
            offset = sum(durations[:i]) - transition * i
            filters.append(
                f"{previous}{labels[i]}xfade=transition=fade:duration={transition:.2f}:"
                f"offset={offset:.3f}{next_label}"
            )
            previous = next_label
        final_label = previous

    filters.append(f"{final_label}null[outv]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[outv]", "-an",
            "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(reel_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown FFmpeg error")[-1800:]
            raise RuntimeError(detail)
        if not reel_path.exists() or reel_path.stat().st_size < 10000:
            raise RuntimeError("FFmpeg produced an empty scene reel.")

        # The existing caption renderer handles narration timing and overlays.
        render(title, words, mp3_path, mp4_path, clip=reel_path)
        print("Rendered scene-matched moving footage with timed captions.")
        return True
    finally:
        if reel_path.exists():
            reel_path.unlink()


def scene_visual_names(texts, title):
    """3D renders when numpy is installed, otherwise the simple 2D animations."""
    try:
        import numpy  # noqa: F401
        return [pick_3d(t, title) for t in texts], True
    except ImportError:
        print("numpy is not installed (pip install numpy): using simple 2D animations instead.")
        return [pick_anim(t, title) for t in texts], False


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--auto", action="store_true", help="refill topics + make + upload")
    a = ap.parse_args()
    if a.auto:
        a.upload = True
        a.privacy = os.environ.get("PRIVACY", a.privacy)

    topics = json.loads(TOPICS.read_text(encoding="utf-8"))
    if a.list:
        for i, t in enumerate(topics):
            print(("[x] " if t.get("done") else "[ ] ") + t["title"])
        return
    if a.auto:
        trends = find_trending()
        if trends:                                   # today's video = a fresh trending idea
            topics = add_topics(topics, 1, trends, front=True)
        topics = refill(topics)
        TOPICS.write_text(json.dumps(topics, indent=2, ensure_ascii=False), encoding="utf-8")
    todo = next((t for t in topics if not t.get("done")), None)
    if not todo:
        print("No topics left. Add more to topics.json")
        return

    OUT.mkdir(exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in todo["title"])[:40]
    mp3, mp4 = OUT / f"{slug}.mp3", OUT / f"{slug}.mp4"

    print("1/3 voice...")
    words = asyncio.run(make_voice(todo["script"], mp3))
    kw = todo.get("keywords") or todo["title"].replace("What if", "").strip(" ?")
    mode = os.environ.get("VISUALS", "auto")   # 3d (default, free) | auto (real photos) | anim | images | stock | plain
    scene_texts = split_visual_pairs(todo["script"])
    scene_imgs, scene_anims, clip, is3d = None, None, None, False
    plan = None
    scene_videos = None
    if mode in ("auto", "images", "stock"):
        print("Planning visuals for each scene...")
        plan = plan_scenes(scene_texts, todo["title"])
    if mode in ("auto", "stock"):
        print("Finding real moving footage for each scene...")
        scene_videos = fetch_scene_videos(scene_texts, plan, slug)
    if mode in ("auto", "images"):
        print("Preparing AI/photo fallbacks for scenes without video...")
        scene_imgs = fetch_scene_visuals(scene_texts, plan, slug)
    if not scene_imgs and not scene_videos and mode in ("auto", "stock"):
        clip = fetch_clip(kw, OUT / f"{slug}_bg.mp4")
    if not clip and mode in ("3d", "anim", "auto", "images"):
        if mode == "anim":
            scene_anims = [pick_anim(t, todo["title"]) for t in scene_texts]
        else:
            scene_anims, is3d = scene_visual_names(scene_texts, todo["title"])
        if not scene_imgs:
            for n, (name, t) in enumerate(zip(scene_anims, scene_texts), 1):
                print(f"  scene {n}/{len(scene_texts)} -> {name}: {t[:50]}")
    print("2/3 rendering video (2-5 minutes)... visuals:",
          "real pictures (3D/animation where none found)" if scene_imgs else "stock video" if clip
          else "3D renders" if is3d else "built-in animations" if scene_anims else "stars background")
    if scene_videos:
        try:
            render_with_scene_videos(todo["title"], words, mp3, mp4, scene_videos, scene_texts, scene_imgs)
        except Exception as e:
            print("Scene-footage renderer failed; switching to safe scene-image renderer:", e)
            render(todo["title"], words, mp3, mp4, clip, scene_imgs, scene_texts, scene_anims)
    else:
        render(todo["title"], words, mp3, mp4, clip, scene_imgs, scene_texts, scene_anims)
    print("Video ready:", mp4)
    validate_video(mp4)

    if a.upload:
        print("3/3 uploading...")
        vid = upload(mp4, todo["title"] + " #Shorts",
                     todo["script"] + "\n\n" + "\n".join(CREDITS) + "\n#Shorts #WhatIf", ["shorts", "what if"], a.privacy)
        print("Uploaded: https://youtube.com/watch?v=" + vid)
        todo["done"] = True
        TOPICS.write_text(json.dumps(topics, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\nERROR:", e)
        sys.exit(1)
